import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import { stageContent, fileUrl, ready, addTextComment, readDownload, openToolbarMenu, PYTHON, SKILL } from "./helpers.js";

// The Python-side hasher reads the SOURCE FILE, so comparing it to the live runtime hash catches a
// load-time transform that changed the hashed text (the pattern CMH-CONTENT-21 established).
const HASH_SRC = [
  "import sys",
  "sys.path.insert(0, 'tools')",
  "from authoring.section_hash import document_content_hash",
  "print(document_content_hash(open(sys.argv[1], encoding='utf-8').read()) or '')",
].join("\n");

function sourceHash(htmlPath) {
  return execFileSync(PYTHON, ["-c", HASH_SRC, path.resolve(htmlPath)], { cwd: SKILL, encoding: "utf8" }).trim();
}

const docHash = (page) => page.evaluate(() => window.__cmhReview.docHash());

// A generated Contents list (the shape generate_toc.py bakes: a nav.cm-toc with a title div, an
// ol.cm-toc-numbered, and a cm-skip number span per entry) followed by the sections it points at.
const CONTENT = `
<nav class="cm-toc" aria-label="Table of contents">
  <div class="cm-toc-title">Contents</div>
  <ol class="cm-toc-numbered" style="list-style: none; padding-left: 0;">
    <li><span class="cm-toc-num cm-skip">1 </span><a href="#alpha">Alpha overview</a></li>
    <li><span class="cm-toc-num cm-skip">2 </span><a href="#beta">Beta details</a></li>
    <li><span class="cm-toc-num cm-skip">3 </span><a href="#gamma">Gamma appendix</a></li>
  </ol>
</nav>
<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2>
  <p id="ap">Apple content describing the first area.</p></section>
<section aria-labelledby="beta"><h2 id="beta">Beta details</h2>
  <p>Banana content describing the second area.</p></section>
<section aria-labelledby="gamma"><h2 id="gamma">Gamma appendix</h2>
  <p>Cherry content mentioning the unique word zebra.</p></section>
`;

const KEY = "cmh-toc-collapse-test";

async function openDoc(page, { key = KEY } = {}) {
  const staged = stageContent(CONTENT, { key, source: "toc-collapse.html" });
  await page.setViewportSize({ width: 1600, height: 800 });
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await expect(page.locator("#commentRoot nav.cm-toc")).toBeVisible();
  return staged;
}

const caret = (page) => page.locator("#commentRoot nav.cm-toc .cmh-toc-caret");
const list = (page) => page.locator("#commentRoot nav.cm-toc ol").first();

test.describe("in-document Contents list is collapsible (CMH-TOC-12)", () => {
  test("the Contents list folds and unfolds from its own caret (CMH-TOC-12)", async ({ page }) => {
    await openDoc(page);
    // Expanded is the default, so an untouched document looks exactly as it always did.
    await expect(list(page)).toBeVisible();
    await expect(caret(page)).toHaveAttribute("aria-expanded", "true");

    await caret(page).click();
    await expect(list(page)).toBeHidden();
    // The title stays put so the collapsed block still says what it is, and the control that
    // brings the list back is still on screen.
    await expect(page.locator("#commentRoot nav.cm-toc .cm-toc-title")).toBeVisible();
    await expect(caret(page)).toBeVisible();
    await expect(caret(page)).toHaveAttribute("aria-expanded", "false");

    await caret(page).click();
    await expect(list(page)).toBeVisible();
    await expect(caret(page)).toHaveAttribute("aria-expanded", "true");
  });

  test("clicking a collapsed Contents title unfolds it (CMH-TOC-12)", async ({ page }) => {
    await openDoc(page);
    await caret(page).click();
    await expect(list(page)).toBeHidden();
    await page.locator("#commentRoot nav.cm-toc .cm-toc-title").click();
    await expect(list(page)).toBeVisible();
  });

  test("the folded Contents list stays folded across a reload (CMH-TOC-12)", async ({ page }) => {
    await openDoc(page);
    await caret(page).click();
    await expect(list(page)).toBeHidden();

    await page.reload();
    await ready(page);
    await expect(list(page)).toBeHidden();
    await expect(caret(page)).toHaveAttribute("aria-expanded", "false");

    // Unfolding is remembered the same way, so the preference is a real toggle and not a one-way door.
    await caret(page).click();
    await page.reload();
    await ready(page);
    await expect(list(page)).toBeVisible();
  });

  test("the folded state is per document, not global (CMH-TOC-12)", async ({ page }) => {
    await openDoc(page);
    await caret(page).click();
    await expect(list(page)).toBeHidden();

    // A different document (its own data-comment-key) is unaffected.
    await openDoc(page, { key: KEY + "-other" });
    await expect(list(page)).toBeVisible();
  });

  test("the Contents caret is text-free chrome, so the document hash is unchanged (CMH-TOC-12)", async ({ page }) => {
    const staged = await openDoc(page);
    // The caret really was injected (else the hash comparison below passes on a no-op).
    await expect(caret(page)).toHaveClass(/\bcm-skip\b/);
    expect(await caret(page).evaluate((el) => el.textContent)).toBe("");

    // The nav lands INSIDE #commentRoot, where comments are anchored by TEXT OFFSET. Comparing the
    // live runtime hash to the SOURCE FILE's hash is the only way to see the "before" the page
    // itself cannot show: a toggle that spent even one character would shift every comment saved
    // below the Contents list.
    expect(await docHash(page)).toBe(sourceHash(staged.html));

    // Folding is a class flip, never a node removal, so it is text-neutral too.
    await caret(page).click();
    await expect(list(page)).toBeHidden();
    expect(await docHash(page)).toBe(sourceHash(staged.html));
  });

  test("a comment below the Contents list keeps its anchor across a reload (CMH-TOC-12)", async ({ page }) => {
    await openDoc(page);
    await addTextComment(page, "#ap", "Anchored below the contents list.");
    const anchored = (await page.locator("#commentRoot mark.cm-hl").first().textContent()) || "";
    expect(anchored.trim().length).toBeGreaterThan(10);

    await caret(page).click();
    await page.reload();
    await ready(page);
    await expect(page.locator("#commentRoot mark.cm-hl")).toHaveCount(1);
    await expect(page.locator("#commentRoot mark.cm-hl")).toHaveText(anchored);
  });

  test("jumping to a comment inside a folded Contents list unfolds it (CMH-TOC-12)", async ({ page }) => {
    await openDoc(page);
    // A Contents entry is ordinary commentable content, so a comment can be anchored on it. Once
    // folded, the entry has no layout box - the jump would silently scroll to nothing.
    await addTextComment(page, '#commentRoot nav.cm-toc a[href="#beta"]', "note on a contents entry");
    await caret(page).click();
    await expect(list(page)).toBeHidden();

    // The fold persists, so the broken jump would be sticky: reload before activating the card.
    await page.reload();
    await ready(page);
    await expect(list(page)).toBeHidden();
    await page.locator(".cm-card").first().click();
    await expect(list(page)).toBeVisible();
    await expect(page.locator("#commentRoot mark.cm-hl")).toBeVisible();
    // Unfolded through the owning toggle, so the caret's state and the stored choice agree.
    await expect(caret(page)).toHaveAttribute("aria-expanded", "true");
    await page.reload();
    await ready(page);
    await expect(list(page)).toBeVisible();
  });

  test("several Contents lists in one document fold independently (CMH-TOC-12)", async ({ page }) => {
    const TWO = CONTENT + `
<nav class="cm-toc" aria-label="Appendix contents">
  <div class="cm-toc-title">Appendix contents</div>
  <ul><li><a href="#gamma">Gamma appendix</a></li></ul>
</nav>`;
    const staged = stageContent(TWO, { key: KEY + "-two", source: "toc-two.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const navs = page.locator("#commentRoot nav.cm-toc");
    await expect(navs).toHaveCount(2);

    await navs.nth(1).locator(".cmh-toc-caret").click();
    await expect(navs.nth(0).locator("ol")).toBeVisible();
    await expect(navs.nth(1).locator("ul")).toBeHidden();

    await page.reload();
    await ready(page);
    await expect(navs.nth(0).locator("ol")).toBeVisible();
    await expect(navs.nth(1).locator("ul")).toBeHidden();
  });

  test("a Contents list with no title still gets a working caret (CMH-TOC-12)", async ({ page }) => {
    const BARE = `
<nav class="cm-toc" aria-label="Table of contents">
  <ol><li><a href="#alpha">Alpha overview</a></li><li><a href="#beta">Beta details</a></li></ol>
</nav>
<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2><p>Apple.</p></section>
<section aria-labelledby="beta"><h2 id="beta">Beta details</h2><p>Banana.</p></section>`;
    const staged = stageContent(BARE, { key: KEY + "-bare", source: "toc-bare.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(caret(page)).toBeVisible();
    // aria-controls names the NAV, so it covers everything the fold actually hides.
    expect(await caret(page).getAttribute("aria-controls"))
      .toBe(await page.locator("#commentRoot nav.cm-toc").getAttribute("id"));
    await caret(page).click();
    await expect(list(page)).toBeHidden();
    await expect(caret(page)).toBeVisible();
  });

  test("a corrupt or polluted fold state leaves the Contents list expanded (CMH-TOC-12)", async ({ page }) => {
    const staged = stageContent(CONTENT, { key: KEY + "-corrupt", source: "toc-corrupt.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const key = await page.locator("#commentRoot nav.cm-toc a").first().getAttribute("href");
    // Only the exact `1` sentinel counts as a fold, so a truthy-but-wrong value cannot hide a
    // reader's Contents list behind a state the runtime cannot reason about.
    for (const bad of ["[1]", "not json", '"1"', "null", `{"${key}":{"x":1}}`, `{"${key}":"1"}`]) {
      await page.evaluate(([k, value]) => {
        localStorage.setItem(k + "::tocFold", value);
      }, [KEY + "-corrupt", bad]);
      await page.reload();
      await ready(page);
      await expect(list(page)).toBeVisible();
      await expect(caret(page)).toHaveAttribute("aria-expanded", "true");
    }

    // A polluted Object.prototype must not fall through into the fold map either - the runtime has
    // ONE convention for a document-reachable state map (CMH-SEC-02) and this map follows it.
    await page.evaluate(() => localStorage.removeItem("does-not-matter"));
    await page.addInitScript((k) => {
      // eslint-disable-next-line no-extend-native
      Object.prototype[k] = 1;
    }, key);
    await page.evaluate(([k]) => localStorage.removeItem(k + "::tocFold"), [KEY + "-corrupt"]);
    await page.reload();
    await ready(page);
    // The pollution really is live (else this would pass on a no-op).
    expect(await page.evaluate((k) => ({})[k], key)).toBe(1);
    await expect(list(page)).toBeVisible();
  });

  test("adding a Contents list above a folded one does not move the fold (CMH-TOC-12)", async ({ page }) => {
    const APPENDIX = `
<nav class="cm-toc" aria-label="Appendix contents">
  <div class="cm-toc-title">Appendix contents</div>
  <ul><li><a href="#gamma">Gamma appendix</a></li></ul>
</nav>`;
    const staged = stageContent(CONTENT + APPENDIX, { key: KEY + "-stable", source: "toc-stable.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const navs = page.locator("#commentRoot nav.cm-toc");
    await navs.nth(1).locator(".cmh-toc-caret").click();
    await expect(navs.nth(1).locator("ul")).toBeHidden();

    // The document gains a THIRD Contents list at the very top. A DOM-index key would now apply the
    // appendix's fold to whichever list happens to sit at that index; a stable identity does not.
    const shifted = fs.readFileSync(staged.html, "utf8").replace(
      '<nav class="cm-toc" aria-label="Table of contents">',
      '<nav class="cm-toc" aria-label="Overview"><div class="cm-toc-title">Overview</div>'
      + '<ol><li><a href="#alpha">Alpha overview</a></li></ol></nav>'
      + '<nav class="cm-toc" aria-label="Table of contents">');
    fs.writeFileSync(staged.html, shifted);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(navs).toHaveCount(3);
    await expect(navs.nth(0).locator("ol")).toBeVisible();
    await expect(navs.nth(1).locator("ol")).toBeVisible();
    await expect(navs.nth(2).locator("ul")).toBeHidden();
  });

  test("a folded Contents list still prints in full (CMH-TOC-12)", async ({ page }) => {
    await openDoc(page);
    await caret(page).click();
    await expect(list(page)).toBeHidden();

    await page.emulateMedia({ media: "print" });
    // A print or a Save as PDF carries the whole authored document, so the reader's transient fold
    // must not remove the Contents list from it - while the toggle itself is screen chrome.
    await expect(list(page)).toBeVisible();
    await expect(caret(page)).toBeHidden();
  });

  test("the Contents caret and fold state never leak into an export (CMH-TOC-12)", async ({ page }) => {
    await openDoc(page);
    await caret(page).click();
    await expect(list(page)).toBeHidden();

    await openToolbarMenu(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#btnSaveHtmlTop")]);
    const out = await readDownload(dl);
    // The exported base is the on-disk source, so the runtime-injected caret node and the fold
    // class must not appear in it. (The layer's own CSS/JS still MENTIONS both names - the export
    // keeps the whole layer - so assert on the rendered markup, not on the bare identifiers.)
    expect(out).not.toContain('class="cmh-toc-caret cm-skip"');
    expect(out).not.toContain("cm-toc cmh-toc-collapsed");
    expect(out).toContain('class="cm-toc"');
    expect(out).toContain("BEGIN: commentable-html - JS"); // the layer is intact (not a plain export)
  });
});
