import { test, expect } from "@playwright/test";
import fs from "fs";
import { execFileSync } from "child_process";
import { stageContent, fileUrl, ready, addTextComment, PYTHON, SKILL } from "./helpers.js";

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
  <p>Walkthrough every quarter before the milestone.</p>
  <h3 id="mitigation">10.4 Mitigation plan</h3>
  <p>Controls and owners.</p>
  <h2 id="rollout">11. Rollout</h2>
  <p>Sequencing notes for the milestone.</p>
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
const linkLeft = async (toc, id) => {
  const box = await tocLink(toc, id).boundingBox();
  if (!box) throw new Error("linkLeft: #" + id + " has no bounding box (not laid out)");
  return box.x;
};

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

  test("the search box filters visible sections by section title only, Escape clears (CMH-TOC-09)", async ({ page }) => {
    const toc = await openDoc(page);
    const search = toc.locator(".cm-side-toc-search");
    await expect(search).toBeVisible();

    // A heading word narrows to its own section, hiding the others and their TOC entries, and the
    // comparison is case-insensitive.
    await search.fill("gamma");
    await expect(sec(page, "gamma")).toBeVisible();
    await expect(sec(page, "alpha")).toBeHidden();
    await expect(sec(page, "beta")).toBeHidden();
    await expect(toc.locator('.cm-side-toc-list a[href="#gamma"]')).toBeVisible();
    await expect(toc.locator('.cm-side-toc-list a[href="#alpha"]')).toBeHidden();

    // A word that appears ONLY in a section's body matches nothing: the reader is filtering the
    // list of section TITLES, so body prose must never keep a section listed.
    await search.fill("zebra");
    await expect(toc.locator(".cm-side-toc-list li:not(.cm-toc-li-hidden)")).toHaveCount(0);

    // Surrounding whitespace is ignored, and so is the exact run of whitespace inside a title.
    await search.fill("  beta   DETAILS ");
    await expect(sec(page, "beta")).toBeVisible();
    await expect(sec(page, "alpha")).toBeHidden();

    // Escape clears the filter and restores every section.
    await search.press("Escape");
    await expect(search).toHaveValue("");
    await expect(sec(page, "alpha")).toBeVisible();
    await expect(sec(page, "beta")).toBeVisible();
    await expect(sec(page, "gamma")).toBeVisible();
  });

  test("the filter ignores the numbering prefix and the review mark the menu renders (CMH-TOC-09)", async ({ page }) => {
    // The menu renders a computed 1.1-style number in its own span and the review status mark as a
    // CSS pseudo-element (CMH-REVIEW-11). Neither belongs to the section title, so neither may
    // match - otherwise typing a number would filter on chrome the document never wrote.
    const PLAIN = `
      <section><h2 id="one">Findings</h2><p>lead</p></section>
      <section><h3 id="one-a">Signals</h3><p>detail</p></section>
      <section><h2 id="two">Next steps</h2><p>lead</p></section>`;
    const toc = await openNested(page, PLAIN, "cmh-toc-num-nomatch");
    await expect(tocNum(toc, "one-a")).toHaveText("1.1");
    await toc.locator(".cm-side-toc-search").fill("1.1");
    await expect(toc.locator(".cm-side-toc-list li:not(.cm-toc-li-hidden)")).toHaveCount(0);
    // The title itself still matches, so the entry is reachable by what the document says.
    await toc.locator(".cm-side-toc-search").fill("signals");
    await expect(tocRow(toc, "one-a")).toBeVisible();
    await expect(tocRow(toc, "two")).toBeHidden();

    // With the review UI active each entry also carries a single-character status mark. It is a
    // pseudo-element, not link text, so a query for it matches nothing (no title here holds an "r").
    await toc.locator(".cm-side-toc-search").fill("");
    const badge = page.locator("#one .cmh-review-badge");
    await expect(badge).toBeAttached();
    await badge.click({ force: true });
    await expect(page.locator("#cmSideToc .cmh-toc-mark").first()).toBeAttached();
    await toc.locator(".cm-side-toc-search").fill("r");
    await expect(toc.locator(".cm-side-toc-list li:not(.cm-toc-li-hidden)")).toHaveCount(0);
  });

  test("the number the document itself supplies is part of the title a query matches (CMH-TOC-09)", async ({ page }) => {
    // The menu row and the heading both read "10.3 Vendor exposure", so typing 10.3 must find it.
    // The number lives in its own span only because generate_toc strips it from the nav label
    // (CMH-TOC-10); it is the DOCUMENT's own number, unlike the sequential one the runtime computes.
    const toc = await openNested(page, NESTED, "cmh-toc-docnum-match");
    await expect(tocNum(toc, "vendor")).toHaveText("10.3");
    await toc.locator(".cm-side-toc-search").fill("10.3");
    await expect(tocRow(toc, "vendor")).toBeVisible();
    // The match is a substring one, as it is for any other title text, so the 10.3.1 subsection
    // stays listed under it; an unrelated top-level number does not.
    await expect(tocRow(toc, "audit")).toBeVisible();
    await expect(tocRow(toc, "mitigation")).toBeHidden();
    await expect(tocRow(toc, "rollout")).toBeHidden();
  });

  test("an icon-only nav entry still matches its heading's own title (CMH-TOC-09)", async ({ page }) => {
    // An author nav link with no text of its own has no label to show or match, so it falls back to
    // the title its heading shows - the row and the filter resolve the same title, so a query can
    // never surface a row whose title the reader cannot read.
    const ICON_NAV = `
      <nav class="cm-toc"><ol>
        <li><a href="#i-one"><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt=""></a></li>
        <li><a href="#i-two">Rollout</a></li>
      </ol></nav>
      <section><h2 id="i-one">10.3 Vendor exposure</h2><p>Third-party surface notes.</p></section>
      <section><h2 id="i-two">Rollout</h2><p>Sequencing notes.</p></section>`;
    const toc = await openNested(page, ICON_NAV, "cmh-toc-icon-nav");
    // The row reads the heading's title, with the document's number in its own span (not twice).
    await expect(tocNum(toc, "i-one")).toHaveText("10.3");
    await expect(tocLink(toc, "i-one")).toHaveText("10.3 Vendor exposure");
    await toc.locator(".cm-side-toc-search").fill("vendor");
    await expect(tocRow(toc, "i-one")).toBeVisible();
    await expect(tocRow(toc, "i-two")).toBeHidden();
    // The number the row shows matches too, and it is stored once - not "10.3 10.3".
    await toc.locator(".cm-side-toc-search").fill("10.3 vendor");
    await expect(tocRow(toc, "i-one")).toBeVisible();
  });

  test("a title broken across source lines matches a normally spaced query (CMH-TOC-09)", async ({ page }) => {
    // Heading text carries the source's own line breaks and indentation. A reader types the words
    // they see, so both sides of the comparison collapse their whitespace runs.
    const WRAPPED = `
      <section><h2 id="w-one">Vendor
            exposure</h2><p>lead</p></section>
      <section><h2 id="w-two">Rollout</h2><p>lead</p></section>`;
    const toc = await openNested(page, WRAPPED, "cmh-toc-wrapped-title");
    await toc.locator(".cm-side-toc-search").fill("vendor exposure");
    await expect(tocRow(toc, "w-one")).toBeVisible();
    await expect(tocRow(toc, "w-two")).toBeHidden();
  });

  test("navigating to a filtered-out section reveals it (CMH-TOC-09)", async ({ page }) => {
    const toc = await openDoc(page);
    await toc.locator(".cm-side-toc-search").fill("Gamma");
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
    await toc.locator(".cm-side-toc-search").fill("Alpha");
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

  test("the in-document Contents list and the side menu show the same number (CMH-TOC-10)", async ({ page }) => {
    // The two surfaces number the SAME headings, so they must agree: the side menu reads the
    // number generate_toc.py baked into the Contents entry instead of computing a second one,
    // and the Contents list no longer leans on a flat ordered-list marker that made a subsection
    // read as a top-level section.
    const BODY = `
      <h1>Quarterly review</h1>
      <h2 id="one">Findings</h2><p>lead</p>
      <h3 id="one-a">Signals</h3><p>detail</p>
      <h3 id="one-b">Sampling</h3><p>detail</p>
      <h2 id="two">Next steps</h2><p>lead</p>`;
    const { html } = stageContent(BODY, { key: "cmh-toc-agree", source: "toc-agree.html" });
    execFileSync(PYTHON, ["tools/authoring/generate_toc.py", "--in-place", html], { cwd: SKILL, stdio: "pipe" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(html));
    await ready(page);
    const toc = page.locator("#cmSideToc");
    await expect(toc).toBeVisible();
    for (const [id, number] of [["one", "1"], ["one-a", "1.1"], ["one-b", "1.2"], ["two", "2"]]) {
      const inDoc = page.locator(`#commentRoot .cm-toc li:has(> a[href="#${id}"]) > .cm-toc-num`);
      await expect(inDoc).toHaveText(number);
      await expect(tocNum(toc, id)).toHaveText(number);
    }
    // The list marker would be that second, flat number, so the generated list drops it.
    const marker = await page.locator("#commentRoot .cm-toc ol").first()
      .evaluate((el) => getComputedStyle(el).listStyleType);
    expect(marker).toBe("none");
  });

  test("a document that numbers its own headings keeps those numbers on both surfaces (CMH-TOC-10)", async ({ page }) => {
    // The generator's second numbering path, end to end: when the headings display their own
    // numbers the Contents list bakes THOSE (not a computed sequence), and the side menu shows the
    // same string - so a document numbered 10 / 10.3 / 11 is never renumbered 1 / 1.1 / 2.
    const BODY = `
      <h1>Risk review</h1>
      <h2 id="risk">10. Risk register</h2><p>lead</p>
      <h3 id="vendor">10.3 Vendor exposure</h3><p>detail</p>
      <h2 id="rollout">11. Rollout</h2><p>lead</p>`;
    const { html } = stageContent(BODY, { key: "cmh-toc-docnum", source: "toc-docnum.html" });
    execFileSync(PYTHON, ["tools/authoring/generate_toc.py", "--in-place", html], { cwd: SKILL, stdio: "pipe" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(html));
    await ready(page);
    const toc = page.locator("#cmSideToc");
    await expect(toc).toBeVisible();
    for (const [id, number] of [["risk", "10"], ["vendor", "10.3"], ["rollout", "11"]]) {
      await expect(page.locator(`#commentRoot .cm-toc li:has(> a[href="#${id}"]) > .cm-toc-num`)).toHaveText(number);
      await expect(tocNum(toc, id)).toHaveText(number);
    }
  });

  test("baking the Contents numbers does not move an existing comment's anchor (CMH-TOC-10)", async ({ page }) => {
    // The number lands inside `#commentRoot`, where a reader's comments are anchored by TEXT
    // OFFSET - so it is `cm-skip` and carries its own separator, adding no counted character.
    // Without that, re-baking an older document's Contents list (what `content_replace.py` ->
    // `finalize.py` does) would shift every comment saved below it onto unrelated text.
    const BODY = `
      <h1>Quarterly review</h1>
      <h2 id="one">Findings</h2><p id="lead">The anchored sentence lives here.</p>
      <h3 id="one-a">Signals</h3><p>detail</p>`;
    const { html } = stageContent(BODY, { key: "cmh-toc-anchor", source: "toc-anchor.html" });
    // Build the canonical nav, then rewind it to the pre-1.829 shape (flat `<ol>`, no baked
    // number) so the ONLY thing the re-bake below changes is the number itself.
    execFileSync(PYTHON, ["tools/authoring/generate_toc.py", "--in-place", html], { cwd: SKILL, stdio: "pipe" });
    const legacy = fs.readFileSync(html, "utf8")
      .replace(/<ol class="cm-toc-numbered"[^>]*>/, "<ol>")
      .replace(/<span class="cm-toc-num[^"]*">[^<]*<\/span> ?/g, "");
    expect(legacy).not.toMatch(/<span class="cm-toc-num/);
    fs.writeFileSync(html, legacy);

    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#lead", "anchored before the numbers were baked");
    const anchored = (await page.locator("#commentRoot mark.cm-hl").first().textContent()) || "";
    expect(anchored.trim().length).toBeGreaterThan(10);

    // Re-bake, then reload the SAME file so the stored offsets are replayed against the rewrite.
    execFileSync(PYTHON, ["tools/authoring/generate_toc.py", "--in-place", html], { cwd: SKILL, stdio: "pipe" });
    await page.goto(fileUrl(html));
    await ready(page);
    await expect(page.locator(`#commentRoot .cm-toc li:has(> a[href="#one-a"]) > .cm-toc-num`)).toHaveText("1.1");
    await expect(page.locator("#commentRoot mark.cm-hl")).toHaveCount(1);
    await expect(page.locator("#commentRoot mark.cm-hl")).toHaveText(anchored);
  });

  test("an author list that repeats its own number in the label shows it once (CMH-TOC-10)", async ({ page }) => {
    // A hand-written contents list can carry BOTH a `.cm-toc-num` and a label that repeats the same
    // number. Reading the span and then rendering the label verbatim would print "7 7. Intro"; the
    // menu drops an EXACT repeat so the number is shown once.
    const BODY = `
      <nav class="cm-toc"><ol>
        <li><span class="cm-toc-num">7</span> <a href="#intro">7. Intro</a></li>
        <li><span class="cm-toc-num">8</span> <a href="#body">8. Body</a></li>
      </ol></nav>
      <section><h2 id="intro">7. Intro</h2><p>lead</p>
      <h2 id="body">8. Body</h2><p>detail</p></section>`;
    const toc = await openNested(page, BODY, "cmh-toc-author-num");
    await expect(tocNum(toc, "intro")).toHaveText("7");
    await expect(tocLink(toc, "intro")).toHaveText("7 Intro");
    await expect(tocLink(toc, "body")).toHaveText("8 Body");
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

    // A title word belonging to one heading matches only that heading - not every heading that
    // happens to share the wrapper section.
    await search.fill("Mitigation");
    await expect(tocRow(toc, "mitigation")).toBeVisible();
    await expect(tocRow(toc, "risk")).toBeVisible();
    await expect(tocRow(toc, "audit")).toBeHidden();
    await expect(tocRow(toc, "rollout")).toBeHidden();

    // A word that lives only in that heading's prose matches nothing at all, even though every
    // heading here shares one wrapper <section>.
    await search.fill("Controls");
    await expect(toc.locator(".cm-side-toc-list li:not(.cm-toc-li-hidden)")).toHaveCount(0);

    // Clearing restores the complete tree.
    await search.press("Escape");
    await expect(search).toHaveValue("");
    for (const id of ["risk", "vendor", "audit", "mitigation", "rollout"]) {
      await expect(tocRow(toc, id)).toBeVisible();
    }
  });

  test("a deep match keeps its ancestors even when a shallower entry matches later (CMH-TOC-09)", async ({ page }) => {
    // The deepest and the shallowest entry share a word in their TITLES.
    const SHARED = NESTED.replaceAll("Audit cadence", "Audit cadence milestone")
      .replaceAll("Rollout", "Rollout milestone");
    const toc = await openNested(page, SHARED, "cmh-toc-two-matches");
    // Two matches at different levels, the DEEPER one first in the list: the level-3 match must
    // still be listed under its own parents, not stranded with no context by the later level-1 match.
    await toc.locator(".cm-side-toc-search").fill("milestone");
    await expect(tocRow(toc, "audit")).toBeVisible();
    await expect(tocRow(toc, "vendor")).toBeVisible();
    await expect(tocRow(toc, "risk")).toBeVisible();
    await expect(tocRow(toc, "rollout")).toBeVisible();
    await expect(tocRow(toc, "mitigation")).toBeHidden();
  });

  test("a match on a parent heading narrows away its non-matching subsections (CMH-TOC-09)", async ({ page }) => {
    const toc = await openNested(page, NESTED, "cmh-toc-parent-match");
    await toc.locator(".cm-side-toc-search").fill("Risk register");
    // The parent itself matches; its subsections do not, so they are narrowed away (ancestors of a
    // match are kept, descendants are not).
    await expect(tocRow(toc, "risk")).toBeVisible();
    await expect(tocRow(toc, "vendor")).toBeHidden();
    await expect(tocRow(toc, "audit")).toBeHidden();
    await expect(tocRow(toc, "mitigation")).toBeHidden();
    await expect(tocRow(toc, "rollout")).toBeHidden();
  });

  test("a query that matches nothing narrows the menu without blanking the document (CMH-TOC-09)", async ({ page }) => {
    const toc = await openNested(page);
    await toc.locator(".cm-side-toc-search").fill("nomatchxyz");
    await expect(toc.locator(".cm-side-toc-list li:not(.cm-toc-li-hidden)")).toHaveCount(0);
    // Every entry shares one wrapper section: hiding it would leave the reader a blank page with
    // nothing but the filter box, so an empty result narrows the MENU only.
    await expect(page.locator("#wrap")).toBeVisible();
    await expect(page.locator("#risk")).toBeVisible();
  });

  test("a deep link to a filtered-out entry inside a visible wrapper reveals it (CMH-TOC-09)", async ({ page }) => {
    const toc = await openNested(page);
    await toc.locator(".cm-side-toc-search").fill("Rollout");
    await expect(tocRow(toc, "mitigation")).toBeHidden();
    await page.evaluate(() => { location.hash = "#mitigation"; });
    await expect(toc.locator(".cm-side-toc-search")).toHaveValue("");
    await expect(tocRow(toc, "mitigation")).toBeVisible();
  });

  test("a flat author contents list still nests by heading tag (CMH-TOC-11)", async ({ page }) => {
    // One flat <ol> listing an h2, an h3 and an h4: the nesting must come from the heading tags,
    // since the nav's own list depth is 1 for every entry.
    const FLAT_NAV = `
      <nav class="cm-toc"><ol>
        <li><a href="#f-one">Scope</a></li>
        <li><a href="#f-two">Inputs</a></li>
        <li><a href="#f-three">Sampling</a></li>
      </ol></nav>
      <h2 id="f-one">Scope</h2><p>lead</p>
      <h3 id="f-two">Inputs</h3><p>detail</p>
      <h4 id="f-three">Sampling</h4><p>detail</p>`;
    const toc = await openNested(page, FLAT_NAV, "cmh-toc-flat-nav");
    await expect(tocRow(toc, "f-two")).toHaveClass(/is-level-2/);
    await expect(tocRow(toc, "f-three")).toHaveClass(/is-level-3/);
    expect(await linkLeft(toc, "f-two")).toBeGreaterThan(await linkLeft(toc, "f-one"));
    expect(await linkLeft(toc, "f-three")).toBeGreaterThan(await linkLeft(toc, "f-two"));
  });

  test("the fallback skips chrome headings and stops indenting at level 6 (CMH-TOC-01, CMH-TOC-11)", async ({ page }) => {
    const DEEP = `
      <h2 id="d2">Two</h2><p>a</p>
      <h3 id="d3">Three</h3><p>b</p>
      <h4 id="d4">Four</h4><p>c</p>
      <div class="cm-skip"><h4 id="chrome-h4">Runtime chrome</h4></div>
      <p>after chrome</p>`;
    const toc = await openNested(page, DEEP, "cmh-toc-deep");
    // A heading inside cm-skip chrome is not a document section, so it is never listed.
    await expect(toc.locator('.cm-side-toc-list a[href="#chrome-h4"]')).toHaveCount(0);
    await expect(tocRow(toc, "d4")).toHaveClass(/is-level-3/);
    // Nothing the filter hides is ever written outside the content root.
    await toc.locator(".cm-side-toc-search").fill("Three");
    expect(await page.evaluate(() => [...document.querySelectorAll(".cm-toc-filtered")]
      .every((el) => document.getElementById("commentRoot").contains(el)))).toBe(true);
  });

  test("a nav nested deeper than the indent steps holds the level-6 indent (CMH-TOC-11)", async ({ page }) => {
    // Seven levels of author list nesting over NON-heading targets, so the level really is 7 and the
    // runtime - not the CSS - must cap the class it emits at 6 (is-level-7 has no rule of its own,
    // which would drop the deepest entry back to the much smaller sub-entry indent).
    let nav = "";
    let body = "";
    for (let i = 1; i <= 7; i++) {
      nav += `<ol><li><a href="#n${i}">Entry ${i}</a>`;
      body += `<div id="n${i}">Body ${i}</div>`;
    }
    for (let i = 1; i <= 7; i++) nav += "</li></ol>";
    const toc = await openNested(page, `<nav class="cm-toc">${nav}</nav>${body}`, "cmh-toc-deep-nav");
    await expect(tocRow(toc, "n6")).toHaveClass(/is-level-6/);
    await expect(tocRow(toc, "n7")).toHaveClass(/is-level-6/);
    await expect(tocRow(toc, "n7")).not.toHaveClass(/is-level-7/);
    expect(await linkLeft(toc, "n7")).toBeCloseTo(await linkLeft(toc, "n6"), 0);
    expect(await linkLeft(toc, "n6")).toBeGreaterThan(await linkLeft(toc, "n5"));
  });

  test("a partly numbered document shows only the numbers it really has (CMH-TOC-11)", async ({ page }) => {
    // One heading carries the document's own number and another does not: the unnumbered one is
    // left unnumbered rather than being given a computed number that would sit in a different
    // scheme beside a real one (and could duplicate it).
    const MIXED = `
      <nav class="cm-toc"><ol>
        <li><a href="#m-one">Overview</a><ol><li><a href="#m-two">Detail</a></li></ol></li>
        <li><a href="#m-three">Next</a></li>
      </ol></nav>
      <h2 id="m-one">10. Overview</h2><p>lead</p>
      <h3 id="m-two">Detail</h3><p>detail</p>
      <h2 id="m-three">11. Next</h2><p>lead</p>`;
    const toc = await openNested(page, MIXED, "cmh-toc-mixed");
    await expect(tocNum(toc, "m-one")).toHaveText("10");
    await expect(tocNum(toc, "m-three")).toHaveText("11");
    await expect(tocLink(toc, "m-two").locator(".cm-toc-num")).toHaveCount(0);
    await expect(tocLink(toc, "m-two")).toContainText("Detail");
    // The hierarchy is still visible even where the number is absent.
    expect(await linkLeft(toc, "m-two")).toBeGreaterThan(await linkLeft(toc, "m-one"));
  });

  test("headings at the same depth stay peers when the document skips a level (CMH-TOC-11)", async ({ page }) => {
    // h2 -> h4 -> h4 -> h3: the two h4 siblings must share a level (and be numbered as peers),
    // and the following h3 must climb back out rather than nesting deeper still.
    const SKIPPED = `
      <h2 id="top">Overview</h2><p>lead</p>
      <h4 id="deep-a">First detail</h4><p>a</p>
      <h4 id="deep-b">Second detail</h4><p>b</p>
      <h3 id="mid">Back out</h3><p>c</p>`;
    const toc = await openNested(page, SKIPPED, "cmh-toc-skipped");
    await expect(tocNum(toc, "top")).toHaveText("1");
    await expect(tocNum(toc, "deep-a")).toHaveText("1.1");
    await expect(tocNum(toc, "deep-b")).toHaveText("1.2");
    await expect(tocNum(toc, "mid")).toHaveText("1.3");
    expect(await linkLeft(toc, "deep-b")).toBeCloseTo(await linkLeft(toc, "deep-a"), 0);
    expect(await linkLeft(toc, "mid")).toBeCloseTo(await linkLeft(toc, "deep-a"), 0);
  });
});
