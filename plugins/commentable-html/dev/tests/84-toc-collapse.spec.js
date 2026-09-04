import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import { stageContent, stageDeck, enterCommentMode, fileUrl, ready, addTextComment, readDownload, openToolbarMenu, PYTHON, SKILL } from "./helpers.js";

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

  test("clicking an expanded Contents title does not fold it, and a selection never unfolds one (CMH-TOC-12)", async ({ page }) => {
    await openDoc(page);
    const title = page.locator("#commentRoot nav.cm-toc .cm-toc-title");
    // The title click is EXPAND-ONLY: on an open list it does nothing, so selecting the title's
    // text to comment on it is unaffected.
    await title.click();
    await expect(list(page)).toBeVisible();
    await expect(caret(page)).toHaveAttribute("aria-expanded", "true");

    // And it is skipped mid-selection. Dispatch the click directly, because a real mouse press
    // collapses the selection before the handler ever sees it.
    await caret(page).click();
    await expect(list(page)).toBeHidden();
    await page.evaluate(() => {
      const range = document.createRange();
      range.selectNodeContents(document.getElementById("ap"));
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      document.querySelector("#commentRoot nav.cm-toc .cm-toc-title")
        .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await expect(list(page)).toBeHidden();

    // With the selection cleared, the same click does unfold it (so the guard, not a dead handler,
    // is what kept it folded).
    await page.evaluate(() => {
      window.getSelection().removeAllRanges();
      document.querySelector("#commentRoot nav.cm-toc .cm-toc-title")
        .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await expect(list(page)).toBeVisible();
  });

  test("two Contents lists sharing an authored id still fold independently (CMH-TOC-12)", async ({ page }) => {
    // Duplicate ids are legal HTML, so the authored-id key must be disambiguated like any other -
    // otherwise both lists read and write one fold and the reader folds two lists with one click.
    const DUPES = `
<nav class="cm-toc" id="contents"><div class="cm-toc-title">Contents</div>
  <ol><li><a href="#alpha">Alpha overview</a></li></ol></nav>
<nav class="cm-toc" id="contents"><div class="cm-toc-title">Contents again</div>
  <ol><li><a href="#beta">Beta details</a></li></ol></nav>
<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2><p>Apple.</p></section>
<section aria-labelledby="beta"><h2 id="beta">Beta details</h2><p>Banana.</p></section>`;
    const staged = stageContent(DUPES, { key: KEY + "-dupe", source: "toc-dupe.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const navs = page.locator("#commentRoot nav.cm-toc");
    await expect(navs).toHaveCount(2);

    await navs.nth(1).locator(".cmh-toc-caret").click();
    await expect(navs.nth(0).locator("ol")).toBeVisible();
    await expect(navs.nth(1).locator("ol")).toBeHidden();

    await page.reload();
    await ready(page);
    await expect(navs.nth(0).locator("ol")).toBeVisible();
    await expect(navs.nth(1).locator("ol")).toBeHidden();

    // The STORAGE identity is disambiguated above; the ARIA relation has to be too. Assistive
    // technology resolves aria-controls with getElementById, which answers with the FIRST element
    // carrying the id, so leaving both carets pointing at the authored `contents` would tell a
    // screen reader the second caret controls a region it does not control.
    const targets = await navs.locator(".cmh-toc-caret").evaluateAll(
      (els) => els.map((el) => el.getAttribute("aria-controls")));
    expect(targets[0]).toBeTruthy();
    expect(targets[1]).toBeTruthy();
    expect(targets[0]).not.toBe(targets[1]);
    // Each id really resolves to the nav its own caret sits in.
    expect(await page.evaluate((ids) => ids.map((id, i) => {
      const navList = document.querySelectorAll("#commentRoot nav.cm-toc");
      return document.getElementById(id) === navList[i];
    }), targets)).toEqual([true, true]);
    // The reader's fold still keys off the AUTHORED id, so re-identifying the nav for ARIA did not
    // orphan the stored choice (the reload above already proved the fold survived).
    expect(await page.evaluate((k) => Object.keys(
      JSON.parse(localStorage.getItem(k + "::tocFold") || "{}")), KEY + "-dupe"))
      .toEqual(["id:contents#1"]);
  });

  test("two Contents lists with identical entries still fold independently (CMH-TOC-12)", async ({ page }) => {
    // No authored id and the SAME entry signature, so both resolve to one identity and are told
    // apart only by their order among themselves.
    const TWIN = `<nav class="cm-toc"><div class="cm-toc-title">Contents</div>
  <ol><li><a href="#alpha">Alpha overview</a></li><li><a href="#beta">Beta details</a></li></ol></nav>`;
    const staged = stageContent(TWIN + TWIN
      + '<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2><p>Apple.</p></section>'
      + '<section aria-labelledby="beta"><h2 id="beta">Beta details</h2><p>Banana.</p></section>',
      { key: KEY + "-twin", source: "toc-twin.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const navs = page.locator("#commentRoot nav.cm-toc");
    await expect(navs).toHaveCount(2);

    await navs.nth(1).locator(".cmh-toc-caret").click();
    await expect(navs.nth(0).locator("ol")).toBeVisible();
    await expect(navs.nth(1).locator("ol")).toBeHidden();

    await page.reload();
    await ready(page);
    await expect(navs.nth(0).locator("ol")).toBeVisible();
    await expect(navs.nth(1).locator("ol")).toBeHidden();
  });

  test("Help scopes the Contents caret to a flow document (CMH-TOC-12)", async ({ page }) => {
    // The Help Navigation topic is the reader-facing surface for this feature (its doc-surface
    // registry entry is `help`), and it drifted once already by promising the caret
    // unconditionally. Pin the two claims that matter: the caret is a FLOW-DOCUMENT affordance,
    // and a deck slide's authored list is left as plain content rather than half-folded.
    await openDoc(page);
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    await expect(page.locator(".cm-help")).toBeVisible();
    const body = page.locator(".cm-help-body");
    await expect(body).toContainText("In a flow document, an in-document Contents list has its own caret");
    await expect(body).toContainText("A deck gets no in-document navigation chrome");
    await expect(body).toContainText("left as plain content, with no caret");
  });

  test("an unrelated earlier element shadowing a Contents id re-identifies the nav (CMH-TOC-12)", async ({ page }) => {
    // The mint's trigger is "this id does not resolve to me", not "another .cm-toc has it", so it
    // fires for ANY earlier owner - here a plain anchor target. Without that, the caret would name
    // the anchor's region. A test that only paired two navs would let the check narrow to a
    // seen-TOC-ids set and still pass.
    const SHADOW = `
<p><a id="contents">Anchor target that borrows the id.</a></p>
<nav class="cm-toc" id="contents" aria-label="Table of contents"><div class="cm-toc-title">Contents</div>
  <ol><li><a href="#alpha">Alpha overview</a></li></ol></nav>
<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2><p>Apple.</p></section>`;
    const staged = stageContent(SHADOW, { key: KEY + "-shadow", source: "toc-shadow.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const nav = page.locator("#commentRoot nav.cm-toc");
    const target = await caret(page).getAttribute("aria-controls");
    expect(target).not.toBe("contents");
    expect(await nav.getAttribute("id")).toBe(target);
    // The caret's target really is the nav, and the earlier anchor keeps the id it authored.
    expect(await page.evaluate((id) =>
      document.getElementById(id) === document.querySelector("#commentRoot nav.cm-toc"), target)).toBe(true);
    expect(await page.evaluate(() =>
      document.getElementById("contents").tagName.toLowerCase())).toBe("a");
    // The fold still works, and is still remembered under the AUTHORED id.
    await caret(page).click();
    await expect(list(page)).toBeHidden();
    expect(await page.evaluate((k) => Object.keys(
      JSON.parse(localStorage.getItem(k + "::tocFold") || "{}")), KEY + "-shadow")).toEqual(["id:contents"]);
  });

  test("an id-less Contents list never steals an authored cmhToc id (CMH-TOC-12)", async ({ page }) => {
    // The mint namespace is not reserved - a document may legitimately author `id="cmhToc0"`. The
    // mint loop therefore probes the whole document before taking a name, so an EARLIER id-less nav
    // cannot claim an id a LATER nav already carries. Without that probe the authored nav would be
    // re-identified on load and an author's `#cmhToc0` rule or link would stop matching it.
    const CLASH = `
<nav class="cm-toc" aria-label="First"><div class="cm-toc-title">Contents</div>
  <ol><li><a href="#alpha">Alpha overview</a></li></ol></nav>
<nav class="cm-toc" id="cmhToc0" aria-label="Second"><div class="cm-toc-title">Appendix</div>
  <ol><li><a href="#beta">Beta details</a></li></ol></nav>
<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2><p>Apple.</p></section>
<section aria-labelledby="beta"><h2 id="beta">Beta details</h2><p>Banana.</p></section>`;
    const staged = stageContent(CLASH, { key: KEY + "-clash", source: "toc-clash.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const navs = page.locator("#commentRoot nav.cm-toc");
    await expect(navs).toHaveCount(2);
    // The authored id survives untouched, and the id-less list took a free name instead.
    await expect(navs.nth(1)).toHaveAttribute("id", "cmhToc0");
    const first = await navs.nth(0).getAttribute("id");
    expect(first).not.toBe("cmhToc0");
    // Both carets still control exactly their own nav.
    const targets = await navs.locator(".cmh-toc-caret").evaluateAll(
      (els) => els.map((el) => el.getAttribute("aria-controls")));
    expect(targets).toEqual([first, "cmhToc0"]);
    expect(await page.evaluate((ids) => ids.map((id, i) => {
      const navList = document.querySelectorAll("#commentRoot nav.cm-toc");
      return document.getElementById(id) === navList[i];
    }), targets)).toEqual([true, true]);
  });

  test("a deck never gets a Contents caret (CMH-TOC-12)", async ({ page }) => {
    // The whole flow-document navigation family (section collapse, the side menu, this fold) is
    // deliberately absent from a deck, whose slides carry their own navigation. Locking the scope
    // here keeps the spec row and the Help text honest: without this the exclusion is incidental,
    // and the reader is promised a caret a deck slide never shows.
    const SLIDES = `
<section class="slide active" aria-labelledby="s1"><h2 id="s1">Agenda</h2>
  <nav class="cm-toc" aria-label="Table of contents"><div class="cm-toc-title">Contents</div>
    Jump to any slide below.
    <ol><li><a href="#s2">Second slide</a></li></ol></nav></section>
<section class="slide" aria-labelledby="s2"><h2 id="s2">Second slide</h2><p>Banana.</p></section>`;
    const staged = stageDeck(SLIDES, { key: KEY + "-deck" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // The deck runtime really did take over (else this passes on a document that is not a deck).
    expect(await page.evaluate(() => !!(window.__cmhDeck && window.__cmhDeck.deckMode))).toBe(true);
    await expect(page.locator("#commentRoot nav.cm-toc")).toHaveCount(1);
    await expect(page.locator("#commentRoot .cmh-toc-caret")).toHaveCount(0);
    // ... and the list is shown in full, not left half-folded by a caret that never arrived.
    await expect(page.locator("#commentRoot nav.cm-toc ol")).toBeVisible();

    // The list is left EXACTLY as written, which includes the delete path: the fold repair in
    // unwrapMarks() is guarded on the nav carrying our caret, so commenting on a deck list's own
    // loose text and then deleting that comment must not leave a wrapper behind either.
    await expect(page.locator("#commentRoot nav.cm-toc .cmh-toc-text")).toHaveCount(0);
    await enterCommentMode(page);
    await addTextComment(page, "#commentRoot nav.cm-toc", "note on the deck contents text");
    await page.reload();
    await ready(page);
    await enterCommentMode(page);
    page.on("dialog", (d) => d.accept());
    await page.locator('.cm-card', { hasText: "note on the deck contents text" }).locator('[data-act="del"]').click();
    await expect(page.locator("#commentRoot mark.cm-hl")).toHaveCount(0);
    await expect(page.locator("#commentRoot .cmh-toc-text")).toHaveCount(0);
    await expect(page.locator("#commentRoot .cmh-toc-caret")).toHaveCount(0);
  });

  test("a folded Contents list hides its own direct text too (CMH-TOC-12)", async ({ page }) => {
    // A hand-authored nav can carry significant text DIRECTLY under `nav.cm-toc`, not only inside
    // its list. The fold rule can only hide ELEMENT children, so such a nav would stay half-folded
    // - the caret says the list is away while a stray sentence is still on screen.
    const TEXTY = `
<nav class="cm-toc" aria-label="Table of contents"><div class="cm-toc-title">Contents</div>
  Jump to any section below.
  <ol><li><a href="#alpha">Alpha overview</a></li><li><a href="#beta">Beta details</a></li></ol>
</nav>
<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2><p>Apple.</p></section>
<section aria-labelledby="beta"><h2 id="beta">Beta details</h2><p>Banana.</p></section>`;
    const staged = stageContent(TEXTY, { key: KEY + "-texty", source: "toc-texty.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // The intro text reads normally while the list is open.
    const intro = page.locator("#commentRoot nav.cm-toc .cmh-toc-text");
    await expect(intro).toHaveText("Jump to any section below.");
    await expect(intro).toBeVisible();

    await caret(page).click();
    await expect(list(page)).toBeHidden();
    await expect(intro).toBeHidden();
    await expect(page.locator("#commentRoot nav.cm-toc .cm-toc-title")).toBeVisible();

    // Wrapping the text must not spend a character of the offset space comments are anchored in,
    // so the live hash still equals the SOURCE file's.
    expect(await docHash(page)).toBe(sourceHash(staged.html));

    await caret(page).click();
    await expect(intro).toBeVisible();
    // Print carries the whole authored list back, the stray text included.
    await caret(page).click();
    await expect(intro).toBeHidden();
    await page.emulateMedia({ media: "print" });
    await expect(intro).toBeVisible();
  });

  test("a non-collapsing space in a Contents list folds away too (CMH-TOC-12)", async ({ page }) => {
    // `trim()` would call this run ignorable, but `&nbsp;` is NOT collapsible whitespace - it
    // paints, so a nav whose loose run is one would keep a stray line box after folding. Source
    // indentation (the newlines and spaces around the markup) must still be left alone, or every
    // ordinary Contents list would gain pointless wrappers.
    const NBSP = `
<nav class="cm-toc" aria-label="Table of contents"><div class="cm-toc-title">Contents</div>
  &nbsp;
  <ol><li><a href="#alpha">Alpha overview</a></li></ol>
</nav>
<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2><p>Apple.</p></section>`;
    const staged = stageContent(NBSP, { key: KEY + "-nbsp", source: "toc-nbsp.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const wrapped = page.locator("#commentRoot nav.cm-toc .cmh-toc-text");
    // Exactly one wrapper: the run carrying the nbsp. The pure-indentation runs around the title
    // and the list are left as bare text nodes.
    await expect(wrapped).toHaveCount(1);
    expect(await wrapped.evaluate((el) => el.textContent.indexOf("\u00a0"))).toBeGreaterThanOrEqual(0);

    await caret(page).click();
    await expect(list(page)).toBeHidden();
    await expect(wrapped).toBeHidden();
    expect(await docHash(page)).toBe(sourceHash(staged.html));
  });

  test("deleting a comment on a Contents list's own text keeps it foldable (CMH-TOC-12)", async ({ page }) => {
    // The wrap is a load-time transform, and a comment RESTORED on that text is re-highlighted
    // long before the wrap runs - so its `mark` lands as a direct child of the nav and the wrap
    // only covers the remainder. Deleting the comment then unwraps that run straight back under
    // the nav, where `normalize()` cannot merge it into the neighbouring wrappers, and the fold
    // (which reaches element children only) would leave it on screen. Both orders are exercised:
    // delete while expanded then fold, and delete while already folded.
    const TEXTY = `
<nav class="cm-toc" aria-label="Table of contents"><div class="cm-toc-title">Contents</div>
  Jump to any section below.
  <ol><li><a href="#alpha">Alpha overview</a></li></ol>
</nav>
<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2><p>Apple.</p></section>`;
    const staged = stageContent(TEXTY, { key: KEY + "-unwrap", source: "toc-unwrap.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const intro = page.locator("#commentRoot nav.cm-toc .cmh-toc-text");
    await expect(intro).toHaveCount(1);

    await addTextComment(page, "#commentRoot nav.cm-toc .cmh-toc-text", "note on the intro line");
    // Reload so the highlight is RESTORED (marked before the wrap runs), which is the ordering
    // that puts the mark directly under the nav.
    await page.reload();
    await ready(page);
    await expect(page.locator("#commentRoot nav.cm-toc > mark.cm-hl")).toHaveCount(1);

    page.on("dialog", (d) => d.accept());
    await page.locator('.cm-card', { hasText: "note on the intro line" }).locator('[data-act="del"]').click();
    await expect(page.locator("#commentRoot mark.cm-hl")).toHaveCount(0);

    // The invariant, asserted directly: no significant run is left as a BARE direct child of the
    // nav, so the fold rule (which reaches element children only) covers all of it. Asserting on
    // rendered text would not do - `toContainText` reads textContent, which includes what the fold
    // has hidden.
    const bareRun = () => page.evaluate(() => {
      const nav = document.querySelector("#commentRoot nav.cm-toc");
      let bare = "";
      for (let n = nav.firstChild; n; n = n.nextSibling) {
        if (n.nodeType === 3 && !/^[\t\n\f\r ]*$/.test(n.nodeValue || "")) bare += n.nodeValue;
      }
      return bare.trim();
    });
    expect(await bareRun()).toBe("");

    // Delete-then-fold: the whole loose run is away, not just the part the load-time wrap caught.
    await caret(page).click();
    await expect(list(page)).toBeHidden();
    await expect(page.locator("#commentRoot nav.cm-toc .cmh-toc-text")).toBeHidden();

    // Fold-then-delete: same guarantee when the list was already folded at deletion time. The
    // delete is driven from the card's own control, so no card-body click is what re-opens it.
    await caret(page).click();
    await addTextComment(page, "#commentRoot nav.cm-toc .cmh-toc-text", "second note on the intro line");
    await page.reload();
    await ready(page);
    await caret(page).click();
    await expect(list(page)).toBeHidden();
    await page.locator('.cm-card', { hasText: "second note on the intro line" }).locator('[data-act="del"]').click();
    await expect(page.locator("#commentRoot mark.cm-hl")).toHaveCount(0);
    // Removing the comment may reopen the list (the delete path reaches its anchor), which is not
    // what this test is about - the invariant is that nothing bare is left behind, so the fold
    // still covers the whole run.
    expect(await bareRun()).toBe("");
    if (await list(page).isVisible()) await caret(page).click();
    await expect(list(page)).toBeHidden();
    await expect(page.locator("#commentRoot nav.cm-toc .cmh-toc-text")).toBeHidden();
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
    // Learn the REAL storage key by folding once and reading what the runtime wrote, rather than
    // re-deriving it here - a test that guessed the key would go vacuously green if it changed.
    await caret(page).click();
    const key = await page.evaluate(([k]) =>
      Object.keys(JSON.parse(localStorage.getItem(k + "::tocFold")))[0], [KEY + "-corrupt"]);
    expect(key).toBeTruthy();

    // Only the exact `1` sentinel counts as a fold, so a truthy-but-wrong value cannot hide a
    // reader's Contents list behind a state the runtime cannot reason about.
    for (const bad of ["[1]", "not json", '"1"', "null", `{${JSON.stringify(key)}:{"x":1}}`,
      `{${JSON.stringify(key)}:"1"}`, `{${JSON.stringify(key)}:true}`]) {
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
    // The list added later repeats the MAIN list's first target, which is the case a key derived
    // from that target alone would collide on - the newcomer would inherit the fold and the folded
    // list would lose it. The key is an entry SIGNATURE, so the two stay distinct.
    const OVERVIEW = '<nav class="cm-toc" aria-label="Overview"><div class="cm-toc-title">Overview</div>'
      + '<ol><li><a href="#alpha">Alpha overview</a></li></ol></nav>';
    const staged = stageContent(CONTENT + APPENDIX, { key: KEY + "-stable", source: "toc-stable.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const navs = page.locator("#commentRoot nav.cm-toc");
    await navs.nth(0).locator(".cmh-toc-caret").click();
    await expect(navs.nth(0).locator("ol")).toBeHidden();

    const shifted = fs.readFileSync(staged.html, "utf8").replace(
      '<nav class="cm-toc" aria-label="Table of contents">',
      OVERVIEW + '<nav class="cm-toc" aria-label="Table of contents">');
    fs.writeFileSync(staged.html, shifted);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(navs).toHaveCount(3);
    // The newcomer is expanded, the list the reader actually folded is still folded, and the
    // untouched appendix is unaffected.
    await expect(navs.nth(0).locator("ol")).toBeVisible();
    await expect(navs.nth(1).locator("ol")).toBeHidden();
    await expect(navs.nth(2).locator("ul")).toBeVisible();
  });

  test("a list whose ends match another's keeps its own fold (CMH-TOC-12)", async ({ page }) => {
    // Same first target, same last target, same count - different middles. A signature built from
    // the ends alone would collide, and the newcomer inserted above would inherit the fold.
    const MAIN = `<nav class="cm-toc"><div class="cm-toc-title">Contents</div><ol>
  <li><a href="#alpha">Alpha overview</a></li>
  <li><a href="#beta">Beta details</a></li>
  <li><a href="#gamma">Gamma appendix</a></li></ol></nav>`;
    const TWIN_ENDS = `<nav class="cm-toc"><div class="cm-toc-title">Highlights</div><ol>
  <li><a href="#alpha">Alpha overview</a></li>
  <li><a href="#delta">Delta notes</a></li>
  <li><a href="#gamma">Gamma appendix</a></li></ol></nav>`;
    const BODY = '<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2><p>Apple.</p></section>'
      + '<section aria-labelledby="beta"><h2 id="beta">Beta details</h2><p>Banana.</p></section>'
      + '<section aria-labelledby="delta"><h2 id="delta">Delta notes</h2><p>Date.</p></section>'
      + '<section aria-labelledby="gamma"><h2 id="gamma">Gamma appendix</h2><p>Cherry.</p></section>';
    const staged = stageContent(MAIN + BODY, { key: KEY + "-ends", source: "toc-ends.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const navs = page.locator("#commentRoot nav.cm-toc");
    await navs.nth(0).locator(".cmh-toc-caret").click();
    await expect(navs.nth(0).locator("ol")).toBeHidden();

    fs.writeFileSync(staged.html, fs.readFileSync(staged.html, "utf8").replace(MAIN, TWIN_ENDS + MAIN));
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(navs).toHaveCount(2);
    await expect(navs.nth(0).locator("ol")).toBeVisible();   // the newcomer did not inherit the fold
    await expect(navs.nth(1).locator("ol")).toBeHidden();    // the list the reader folded still is
  });

  test("jumping into a nested folded Contents list opens every folded ancestor (CMH-TOC-12)", async ({ page }) => {
    // A `.cm-toc` can be nested inside another list's item. Opening only the inner one would leave
    // the comment hidden inside a still-folded outer list, so the jump would still be a no-op.
    const NESTED = `<nav class="cm-toc"><div class="cm-toc-title">Contents</div><ol>
  <li><a href="#alpha">Alpha overview</a>
    <nav class="cm-toc"><div class="cm-toc-title">Sub contents</div>
      <ol><li><a href="#beta">Beta details</a></li></ol></nav></li>
  </ol></nav>
<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2><p>Apple.</p></section>
<section aria-labelledby="beta"><h2 id="beta">Beta details</h2><p>Banana.</p></section>`;
    const staged = stageContent(NESTED, { key: KEY + "-nested", source: "toc-nested.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const outer = page.locator("#commentRoot > nav.cm-toc, #commentRoot nav.cm-toc").first();
    const inner = page.locator("#commentRoot nav.cm-toc nav.cm-toc");
    await expect(inner).toHaveCount(1);

    await addTextComment(page, '#commentRoot nav.cm-toc nav.cm-toc a[href="#beta"]', "note on a nested entry");
    // Fold the INNER list first, then the outer one, so both folds persist.
    await inner.locator(".cmh-toc-caret").click();
    await outer.locator(".cmh-toc-caret").first().click();
    await page.reload();
    await ready(page);
    await expect(outer.locator("> ol")).toBeHidden();

    await page.locator(".cm-card").first().click();
    await expect(outer.locator("> ol")).toBeVisible();
    await expect(inner.locator("ol")).toBeVisible();
    await expect(page.locator("#commentRoot mark.cm-hl")).toBeVisible();
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
