import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
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
