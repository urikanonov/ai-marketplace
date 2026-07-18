// Diff / code-review layer: rendering, side-by-side <-> inline toggle, and
// structural (layout-stable, reload-stable) comments on diff lines.
import { test, expect } from "@playwright/test";
import { openInline, ready, copiedBundle, denyExternalNetwork, fileUrl, INLINE, installClipboardCapture ,
  clickSidebarExport } from "./helpers.js";
import fs from "fs";
import os from "os";
import path from "path";

// Build a temp copy of the inline template with the demo diff replaced by a
// crafted unified diff, so setupDiffLayer parses exactly what we want. Every temp
// file is tracked and removed in afterEach so a failing assertion never leaks one.
const _tempDocs = [];
function docWithDiff(diffText, label = "probe.sql") {
  const tpl = fs.readFileSync(INLINE, "utf8");
  const replaced = tpl.replace(
    /<pre class="cmh-diff"[\s\S]*?<\/pre>/,
    `<pre class="cmh-diff" data-diff-label="${label}">${diffText}</pre>`);
  const out = path.join(os.tmpdir(), "cmh-diff-probe-" + Date.now() + "-" + Math.random().toString(36).slice(2) + ".html");
  fs.writeFileSync(out, replaced);
  _tempDocs.push(out);
  return out;
}

test.afterEach(() => {
  while (_tempDocs.length) {
    try { fs.unlinkSync(_tempDocs.pop()); } catch (e) { /* already removed */ }
  }
});

// Hover a diff line and attach a comment through the "+ comment" affordance.
async function addDiffComment(page, lineSelector, note) {
  await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) throw new Error("no diff line for " + sel);
    el.scrollIntoView({ block: "center" });
    el.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: 50, clientY: 50 }));
  }, lineSelector);
  await expect(page.locator("#diffAddBtn")).toBeVisible();
  await page.locator("#diffAddBtn").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toBeHidden();
}

async function waitForBothSplitPaneHighlights(page) {
  return await page.waitForFunction(() => {
    const byCid = new Map();
    document.querySelectorAll(".cmh-dl-hl[data-cid]").forEach((el) => {
      const cid = el.getAttribute("data-cid");
      if (!cid) return;
      const sides = byCid.get(cid) || new Set();
      sides.add(el.getAttribute("data-side"));
      byCid.set(cid, sides);
    });
    for (const [cid, sides] of byCid) {
      if (sides.has("old") && sides.has("new")) return cid;
    }
    return false;
  }, null, { timeout: 5000 });
}

// Select a [subStart, subEnd) region of a diff line's code and open the popup, so
// a comment anchors to that region (sub-line selection, like regular text).
async function selectDiffRegion(page, lineSelector, subStart, subEnd) {
  await page.evaluate(({ sel, s, e }) => {
    const line = document.querySelector(sel);
    const code = line.querySelector(".cmh-dl-code");
    const r = document.createRange();
    let acc = 0, started = false, done = false;
    const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT, null);
    let n;
    while ((n = walker.nextNode())) {
      const len = n.data.length;
      if (!started && s <= acc + len) { r.setStart(n, s - acc); started = true; }
      if (started && e <= acc + len) { r.setEnd(n, e - acc); done = true; break; }
      acc += len;
    }
    if (!done) throw new Error("could not build region range");
    const selc = window.getSelection(); selc.removeAllRanges(); selc.addRange(r);
    line.closest(".cmh-diff-host").dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  }, { sel: lineSelector, s: subStart, e: subEnd });
  await expect(page.locator("#menuComment")).toBeVisible();
}

async function addDiffRegionComment(page, lineSelector, subStart, subEnd, note) {
  await selectDiffRegion(page, lineSelector, subStart, subEnd);
  await page.locator("#menuComment").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toBeHidden();
}

test.describe("diff region (sub-line) comments", () => {
  const DOC = "@@ -1 +1 @@\n-old value here\n+new value here"; // add-line text: "new value here"

  test("commenting on a selected region wraps just that substring in a mark", async ({ page }) => {
    const doc = docWithDiff(DOC, "sub.txt");
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffRegionComment(page, ".cmh-dl-add", 4, 9, "on the value"); // "value"
    const mark = page.locator("mark.cmh-dl-mark");
    await expect(mark).toHaveCount(1);
    await expect(mark).toHaveText("value");
    await expect(page.locator(".cm-card").filter({ hasText: "on the value" })).toHaveCount(1);
  });

  test("a diff line can carry multiple region comments", async ({ page }) => {
    const doc = docWithDiff(DOC, "multi.txt");
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffRegionComment(page, ".cmh-dl-add", 0, 3, "on new");   // "new"
    await addDiffRegionComment(page, ".cmh-dl-add", 4, 9, "on value"); // "value"
    await expect(page.locator("mark.cmh-dl-mark")).toHaveCount(2);
    await expect(page.locator(".cm-card")).toHaveCount(2);
  });

  test("two ADJACENT regions render as two separate marks (no empty nested mark)", async ({ page }) => {
    const doc = docWithDiff(DOC, "adjacent.txt");
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffRegionComment(page, ".cmh-dl-add", 0, 3, "on new");    // "new"
    await addDiffRegionComment(page, ".cmh-dl-add", 3, 9, "on _value"); // " value" (shares boundary 3)
    await expect(page.locator("mark.cmh-dl-mark")).toHaveCount(2);
    await expect(page.locator("mark.cmh-dl-mark mark.cmh-dl-mark")).toHaveCount(0); // no nesting
    await page.reload();
    await ready(page);
    await expect(page.locator("mark.cmh-dl-mark")).toHaveCount(2);
  });

  test("selecting the same region re-opens its comment for editing (no duplicate)", async ({ page }) => {
    const doc = docWithDiff(DOC, "reopen.txt");
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffRegionComment(page, ".cmh-dl-add", 4, 9, "first");
    await selectDiffRegion(page, ".cmh-dl-add", 4, 9); // same region
    await page.locator("#menuComment").click();
    const composer = page.locator(".cm-composer").last();
    await expect(composer.locator("textarea")).toHaveValue("first"); // edit mode
    await composer.locator("textarea").fill("edited");
    await composer.locator('[data-act="save"]').click();
    await expect(page.locator("mark.cmh-dl-mark")).toHaveCount(1); // still one, not two
    await expect(page.locator(".cm-card").filter({ hasText: "edited" })).toHaveCount(1);
    // The edit persists and re-applies to the same region on reload.
    await page.reload();
    await ready(page);
    await expect(page.locator("mark.cmh-dl-mark")).toHaveCount(1);
    await expect(page.locator(".cm-card").filter({ hasText: "edited" })).toHaveCount(1);
  });

  test("a region comment survives layout toggle and reload", async ({ page }) => {
    const doc = docWithDiff(DOC, "persist.txt");
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffRegionComment(page, ".cmh-dl-add", 4, 9, "persist");
    const cid = await page.locator("mark.cmh-dl-mark").getAttribute("data-cid");
    await page.locator(".cmh-diff-toggle").click(); // split
    await expect(page.locator(`mark.cmh-dl-mark[data-cid="${cid}"]`)).toHaveText("value");
    await page.reload();
    await ready(page);
    await expect(page.locator(`mark.cmh-dl-mark[data-cid="${cid}"]`)).toHaveText("value");
  });

  test("a region comment and a whole-line comment coexist on the same line", async ({ page }) => {
    const doc = docWithDiff(DOC, "coexist.txt");
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffComment(page, ".cmh-dl-add", "whole line"); // +button -> row highlight
    await addDiffRegionComment(page, ".cmh-dl-add", 4, 9, "region"); // mark
    await expect(page.locator(".cmh-dl-add.cmh-dl-hl")).toHaveCount(1);
    await expect(page.locator("mark.cmh-dl-mark")).toHaveCount(1);
    await expect(page.locator(".cm-card")).toHaveCount(2);
  });

  test("Copy all for a region comment quotes only the selected substring, not the whole line", async ({ page }) => {
    const doc = docWithDiff(DOC, "copy.txt");
    await installClipboardCapture(page);
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffRegionComment(page, ".cmh-dl-add", 4, 9, "region copy"); // "value"
    await page.click("#btnCopyAll");
    const bundle = await copiedBundle(page);
    expect(bundle).toContain("value");
    expect(bundle).not.toContain("+new value here"); // not the whole signed line
  });

  test("a poisoned negative subStart in a persisted region comment does not crash init", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("commentable-html-demo", JSON.stringify([
        { id: "cbad00001", anchorType: "diff", diffIndex: 0, lineKey: "0",
          subStart: -1, subEnd: 5, note: "negative poison", createdAt: new Date().toISOString() },
      ]));
    });
    await page.goto(fileUrl(INLINE));
    await ready(page); // hangs if setupDiffLayer/wrapDiffSubRange threw
    await expect(page.locator(".cmh-diff-view")).toHaveCount(1);
  });

  test("two whole-line comments on one diff row: delete-one keeps the highlight, reload restores both", async ({ page }) => {
    const doc = docWithDiff("@@ -1 +1 @@\n-old\n+new", "multi-wl.txt");
    page.on("dialog", (d) => d.accept());
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffComment(page, ".cmh-dl-add", "first wl");
    await addDiffComment(page, ".cmh-dl-add", "second wl");
    const row = page.locator(".cmh-dl-add.cmh-dl-hl");
    expect((await row.getAttribute("data-cids")).split(/\s+/).filter(Boolean)).toHaveLength(2);
    await page.locator(".cm-card").filter({ hasText: "first wl" }).locator('[data-act="del"]').click();
    await expect(row).toHaveClass(/cmh-dl-hl/); // still highlighted (one remains)
    await page.reload();
    await ready(page);
    await expect(page.locator(".cm-card")).toHaveCount(1);
  });

  test("a region comment on a context line marks BOTH split sides", async ({ page }) => {
    const doc = docWithDiff("@@ -1,3 +1,3 @@\n ctxline here\n-old\n+new", "ctx-region.txt");
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffRegionComment(page, '.cmh-dl-ctx[data-side="old"]', 0, 7, "on ctx"); // "ctxline"
    const cid = await page.locator("mark.cmh-dl-mark").first().getAttribute("data-cid");
    await page.reload();
    await ready(page);
    // The mark lives inside the code span; the row carries data-side. Both the old
    // and new copies of the context line get the mark.
    await expect(page.locator(`.cmh-dl[data-side="old"] mark.cmh-dl-mark[data-cid="${cid}"]`)).toHaveCount(1);
    await expect(page.locator(`.cmh-dl[data-side="new"] mark.cmh-dl-mark[data-cid="${cid}"]`)).toHaveCount(1);
  });

  test("a region overlapping an existing region is rejected (no nested marks)", async ({ page }) => {
    const doc = docWithDiff(DOC, "overlap.txt");
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffRegionComment(page, ".cmh-dl-add", 0, 5, "first region"); // "new v"
    // A partially-overlapping region [3,9) must be rejected with a toast, not nested.
    await selectDiffRegion(page, ".cmh-dl-add", 3, 9);
    await page.locator("#menuComment").click();
    await expect(page.locator("#toast")).toContainText(/overlaps an existing comment/i);
    await expect(page.locator("mark.cmh-dl-mark")).toHaveCount(1); // only the first
    await expect(page.locator("mark.cmh-dl-mark mark.cmh-dl-mark")).toHaveCount(0); // no nesting
  });

  test("persisted overlapping region comments do not nest marks on reload", async ({ page }) => {
    // A crafted/legacy comment set with overlapping regions bypasses the create-time
    // guard; the apply-time guard must still prevent nested marks on load.
    const doc = docWithDiff(DOC, "persist-overlap.txt"); // add line "new value here" (key "2")
    await page.addInitScript(() => {
      localStorage.setItem("commentable-html-demo", JSON.stringify([
        { id: "covlap001", anchorType: "diff", diffIndex: 0, lineKey: "2", side: "new", lineType: "add",
          subStart: 0, subEnd: 10, quote: "new value ", note: "A", createdAt: new Date().toISOString() },
        { id: "covlap002", anchorType: "diff", diffIndex: 0, lineKey: "2", side: "new", lineType: "add",
          subStart: 5, subEnd: 14, quote: "value here", note: "B", createdAt: new Date().toISOString() },
      ]));
    });
    await page.goto(fileUrl(doc));
    await ready(page); // must not crash
    await expect(page.locator("mark.cmh-dl-mark mark.cmh-dl-mark")).toHaveCount(0); // no nesting
    await expect(page.locator("mark.cmh-dl-mark")).toHaveCount(1); // only the first-applied region
    await expect(page.locator(".cm-card")).toHaveCount(2); // both comments still listed
  });
});

test.describe("diff rendering", () => {
  test("a pre.cmh-diff renders into a colored review view with add/del/context lines", async ({ page }) => {
    await openInline(page);
    const view = page.locator(".cmh-diff-view");
    await expect(view).toHaveCount(1);
    // The raw <pre class="cmh-diff"> was replaced by a rendered host.
    await expect(page.locator("pre.cmh-diff")).toHaveCount(0);
    await expect(page.locator(".cmh-diff-host")).toHaveCount(1);
    await expect(page.locator(".cmh-dl-add").first()).toBeVisible();
    await expect(page.locator(".cmh-dl-del").first()).toBeVisible();
    await expect(page.locator(".cmh-dl-ctx").first()).toBeVisible();
    // The file label from data-diff-label is shown.
    await expect(page.locator(".cmh-diff-label")).toContainText("src/reducer.py");
    // The raw diff is preserved for re-render/export.
    await expect(page.locator("script.cmh-diff-src")).toHaveCount(1);
  });

  test("diffs default to side-by-side and the toggle switches to inline (persisted)", async ({ page }) => {
    await openInline(page);
    const view = page.locator(".cmh-diff-view");
    // Default is side-by-side (split): old/new cells are present.
    await expect(view).toHaveClass(/cmh-diff-split/);
    await expect(page.locator('.cmh-dl[data-side="old"]').first()).toBeVisible();
    await expect(page.locator('.cmh-dl[data-side="new"]').first()).toBeVisible();

    await page.locator(".cmh-diff-toggle").click();
    await expect(page.locator(".cmh-diff-view")).toHaveClass(/cmh-diff-inline/);
    // Inline uses a single unified pane; no per-side grid cells.
    await expect(page.locator('.cmh-dl[data-side="old"]')).toHaveCount(0);

    // The inline preference persists across reload.
    await page.reload();
    await ready(page);
    await expect(page.locator(".cmh-diff-view")).toHaveClass(/cmh-diff-inline/);

    await page.locator(".cmh-diff-toggle").click();
    await expect(page.locator(".cmh-diff-view")).toHaveClass(/cmh-diff-split/);
  });
});

test.describe("diff comments", () => {
  test("commenting on a diff line highlights it and lists a diff card", async ({ page }) => {
    await openInline(page);
    await addDiffComment(page, ".cmh-dl-add", "This handles the None seed value.");

    const hl = page.locator(".cmh-dl-hl");
    await expect(hl.first()).toBeVisible();
    const cid = await hl.first().getAttribute("data-cid");
    expect(cid).toBeTruthy();

    const card = page.locator(`.cm-card[data-cid="${cid}"]`);
    await expect(card).toHaveCount(1);
    await expect(card).toContainText("This handles the None seed value.");
    // Pinpoint shows the file + an added-line locator.
    await expect(card.locator(".pin")).toContainText("src/reducer.py");
    await expect(card.locator(".pin")).toContainText("+");
  });

  test("a diff comment survives the layout toggle", async ({ page }) => {
    await openInline(page);
    await addDiffComment(page, ".cmh-dl-add", "survives toggle");
    const cid = await page.locator(".cmh-dl-hl").first().getAttribute("data-cid");

    // Default is split; the highlight is visible there and after toggling to inline.
    await expect(page.locator(".cmh-diff-view")).toHaveClass(/cmh-diff-split/);
    await expect(page.locator(`.cmh-dl-hl[data-cid="${cid}"]`).first()).toBeVisible();

    await page.locator(".cmh-diff-toggle").click(); // -> inline
    await expect(page.locator(".cmh-diff-view")).toHaveClass(/cmh-diff-inline/);
    await expect(page.locator(`.cmh-dl-hl[data-cid="${cid}"]`).first()).toBeVisible();
  });

  test("a diff comment survives reload", async ({ page }) => {
    await openInline(page);
    await addDiffComment(page, ".cmh-dl-del", "removed loop body concern");
    const cid = await page.locator(".cmh-dl-hl").first().getAttribute("data-cid");

    await page.reload();
    await ready(page);
    await expect(page.locator(`.cmh-dl-hl[data-cid="${cid}"]`).first()).toBeVisible();
    await expect(page.locator(`.cm-card[data-cid="${cid}"]`)).toHaveCount(1);
  });

  test("Copy all emits the diff anchor and the quoted diff line", async ({ page }) => {
    await openInline(page);
    await addDiffComment(page, ".cmh-dl-add", "check the seed handling");
    await page.click("#btnCopyAll");
    const bundle = await copiedBundle(page);
    expect(bundle).toContain("(diff)");
    expect(bundle).toContain("Anchor: diff src/reducer.py");
    expect(bundle).toContain("```diff");
    expect(bundle).toContain("check the seed handling");
  });
});

test("the diff view remains usable when external requests are denied", async ({ page }) => {
  await denyExternalNetwork(page);
  await page.goto(fileUrl(INLINE));
  await ready(page);
  await addDiffComment(page, ".cmh-dl-add", "self-contained");
  await page.locator(".cmh-diff-toggle").click();
  // The demo page also ships an optional mermaid CDN loader; diff interactions
  // should not depend on additional remote assets, so nothing non-mermaid may appear.
  const nonMermaid = page.__external.filter((u) => !u.includes("mermaid"));
  expect(nonMermaid).toEqual([]);
});

test.describe("diff comment lifecycle", () => {
  test("editing a diff comment updates the note but preserves the anchor fields", async ({ page }) => {
    await openInline(page);
    await addDiffComment(page, ".cmh-dl-add", "first note");
    const cid = await page.locator(".cmh-dl-hl").first().getAttribute("data-cid");
    const before = await page.evaluate((id) => {
      const c = JSON.parse(localStorage.getItem(document.getElementById("commentRoot").dataset.commentKey)).find((x) => x.id === id);
      return { anchorType: c.anchorType, diffIndex: c.diffIndex, lineKey: c.lineKey, oldNo: c.oldNo, newNo: c.newNo };
    }, cid);

    await page.locator(`.cm-card[data-cid="${cid}"] [data-act="edit"]`).click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("edited note");
    await composer.locator('[data-act="save"]').click();

    await expect(page.locator(`.cm-card[data-cid="${cid}"] .note`)).toHaveText("edited note");
    const after = await page.evaluate((id) => {
      const c = JSON.parse(localStorage.getItem(document.getElementById("commentRoot").dataset.commentKey)).find((x) => x.id === id);
      return { anchorType: c.anchorType, diffIndex: c.diffIndex, lineKey: c.lineKey, oldNo: c.oldNo, newNo: c.newNo, note: c.note, hasUpdated: !!c.updatedAt };
    }, cid);
    expect(after.anchorType).toBe(before.anchorType);
    expect(after.diffIndex).toBe(before.diffIndex);
    expect(after.lineKey).toBe(before.lineKey);
    expect(after.oldNo).toBe(before.oldNo);
    expect(after.newNo).toBe(before.newNo);
    expect(after.note).toBe("edited note");
    expect(after.hasUpdated).toBe(true);
  });

  test("deleting a diff comment clears its highlight", async ({ page }) => {
    await openInline(page);
    await addDiffComment(page, ".cmh-dl-add", "to delete");
    const cid = await page.locator(".cmh-dl-hl").first().getAttribute("data-cid");
    page.on("dialog", (d) => d.accept());
    await page.locator(`.cm-card[data-cid="${cid}"] [data-act="del"]`).click();
    await expect(page.locator(`.cm-card[data-cid="${cid}"]`)).toHaveCount(0);
    await expect(page.locator(`.cmh-dl-hl[data-cid="${cid}"]`)).toHaveCount(0);
  });

  test("a comment on a context line highlights BOTH panes in side-by-side view", async ({ page }) => {
    await openInline(page);
    await expect(page.locator(".cmh-diff-view")).toHaveClass(/cmh-diff-split/); // default is split
    // A context line appears once per side (old + new) sharing one logical lineKey.
    await addDiffComment(page, '.cmh-dl-ctx[data-side="old"]', "on a shared context line");
    const cid = await (await waitForBothSplitPaneHighlights(page)).jsonValue();
    // Both the old-side and new-side elements for that line get the same cid.
    await expect(page.locator(`.cmh-dl-hl[data-cid="${cid}"][data-side="old"]`)).toHaveCount(1);
    await expect(page.locator(`.cmh-dl-hl[data-cid="${cid}"][data-side="new"]`)).toHaveCount(1);
  });
});

test.describe("diff parser robustness", () => {
  test("a deleted line whose content starts with '-- ' is a del line, not a file header", async ({ page }) => {
    // Body lines that render as "--- x" / "+++ x" (deleting/adding a "-- x"/"++ x"
    // line, e.g. SQL/Lua comments) must be classified as del/add, not file headers.
    const doc = docWithDiff("@@ -1,3 +1,3 @@\n SELECT 1;\n-- old comment\n+-- new comment\n SELECT 2;", "probe.sql");
    await installClipboardCapture(page);
    await page.goto(fileUrl(doc));
    await ready(page);
    await expect(page.locator(".cmh-diff-view")).toHaveCount(1);
    // The "-- old comment" line is a deletion, rendered as a commentable del row.
    const delLine = page.locator(".cmh-dl-del").filter({ hasText: "- old comment" });
    await expect(delLine.first()).toBeVisible();
    // Its line numbers are not desynced: it is old line 2, and Copy all reports it.
    await addDiffComment(page, ".cmh-dl-del", "comment on the -- del line");
    await page.click("#btnCopyAll");
    const bundle = await copiedBundle(page);
    expect(bundle).toContain("removed line 2");
    fs.unlinkSync(doc);
  });

  test("a second file section after a hunk still parses its headers (multi-file diff)", async ({ page }) => {
    const doc = docWithDiff(
      "diff --git a/one.txt b/one.txt\n--- a/one.txt\n+++ b/one.txt\n@@ -1 +1 @@\n-alpha\n+beta\n" +
      "diff --git a/two.txt b/two.txt\n--- a/two.txt\n+++ b/two.txt\n@@ -1 +1 @@\n-gamma\n+delta", "multi");
    await page.goto(fileUrl(doc));
    await ready(page);
    // Both hunks' add/del lines render (the 2nd file's --- / +++ headers were not
    // swallowed as del/add, and its body lines were not misread as headers).
    await expect(page.locator(".cmh-dl-del").filter({ hasText: "alpha" })).toHaveCount(1);
    await expect(page.locator(".cmh-dl-add").filter({ hasText: "delta" })).toHaveCount(1);
    await expect(page.locator(".cmh-dl-file").filter({ hasText: "two.txt" }).first()).toBeVisible();
    fs.unlinkSync(doc);
  });
  test("a diff line containing a triple-backtick uses a longer Copy-all fence", async ({ page }) => {
    // A diff line whose content contains ``` must not break out of the ```diff fence.
    const doc = docWithDiff("@@ -1,2 +1,2 @@\n context\n+see ``` here", "fence.md");
    await installClipboardCapture(page);
    await page.goto(fileUrl(doc));
    await ready(page);
    await addDiffComment(page, ".cmh-dl-add", "fence test");
    await page.click("#btnCopyAll");
    const bundle = await copiedBundle(page);
    // The opening fence is >=4 backticks (longer than the ``` in the content).
    expect(bundle).toMatch(/`{4,}diff/);
    // The comment note still lands after the closing fence (no premature break-out).
    expect(bundle).toContain("fence test");
    fs.unlinkSync(doc);
  });

  test("a git-LESS multi-file diff parses the 2nd file's headers correctly", async ({ page }) => {
    // No diff --git / index markers between files - only --- / +++ / @@. The 2nd
    // file's headers must be classified as file rows, not del/add body lines.
    const doc = docWithDiff(
      "--- a/one.txt\n+++ b/one.txt\n@@ -1 +1 @@\n-alpha\n+beta\n" +
      "--- a/two.txt\n+++ b/two.txt\n@@ -1 +1 @@\n-gamma\n+delta", "gitless");
    await page.goto(fileUrl(doc));
    await ready(page);
    await expect(page.locator(".cmh-dl-file").filter({ hasText: "two.txt" }).first()).toBeVisible();
    await expect(page.locator(".cmh-dl-del").filter({ hasText: "two.txt" })).toHaveCount(0);
    await expect(page.locator(".cmh-dl-add").filter({ hasText: "two.txt" })).toHaveCount(0);
    await expect(page.locator(".cmh-dl-del").filter({ hasText: "gamma" })).toHaveCount(1);
    fs.unlinkSync(doc);
  });
});

test("a large diff renders as inert raw text instead of freezing", async ({ page }) => {
  let raw = "@@ -1,3000 +1,3000 @@\n";
  for (let i = 0; i < 3000; i++) raw += "-old line " + i + "\n+new line " + i + "\n";
  const doc = docWithDiff(raw.trimEnd(), "huge.txt");
  await page.goto(fileUrl(doc));
  await ready(page);
  await expect(page.locator(".cmh-diff-view")).toHaveClass(/cmh-diff-raw/);
  await expect(page.locator(".cmh-diff-toobig")).toContainText("Large diff");
  await expect(page.locator("pre.cmh-diff-raw")).toHaveCount(1);
  await expect(page.locator(".cmh-dl")).toHaveCount(0);
  await expect(page.locator(".cmh-diff-toggle")).toHaveCount(0);
  fs.unlinkSync(doc);
});

test("a text comment after a diff keeps its anchor across reload (no offset drift)", async ({ page }) => {
  await openInline(page);
  const q = "handled in this HTML";
  await page.evaluate((needle) => {
    const p = [...document.querySelectorAll("#commentRoot p")].find((e) => e.textContent.includes(needle));
    const tn = [...p.childNodes].find((n) => n.nodeType === 3 && n.data.includes(needle));
    const start = tn.data.indexOf(needle);
    const r = document.createRange();
    r.setStart(tn, start); r.setEnd(tn, start + needle.length);
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 40, clientY: 40 }));
  }, q);
  await page.locator("#menuComment").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill("after-diff text comment");
  await composer.locator('[data-act="save"]').click();
  await expect(page.locator("mark.cm-hl").filter({ hasText: q })).toHaveCount(1);
  await page.reload();
  await ready(page);
  // The restored highlight lands on the SAME text (offsets consistent because the
  // diff is .cm-skip before offsets are computed on both save and reload).
  await expect(page.locator("mark.cm-hl").filter({ hasText: q })).toHaveCount(1);
});

test("a diff line is keyboard-commentable (focus + Enter)", async ({ page }) => {
  await openInline(page);
  const line = page.locator(".cmh-dl-add").first();
  await line.focus();
  await expect(page.locator("#diffAddBtn")).toBeVisible();
  await line.press("Enter");
  const composer = page.locator(".cm-composer").last();
  await expect(composer).toBeVisible();
  await composer.locator("textarea").fill("keyboard comment");
  await composer.locator('[data-act="save"]').click();
  await expect(page.locator(".cmh-dl-hl").first()).toBeVisible();
});

test("the diff add button stays centered on the hovered row (CMH-DIFF-11)", async ({ page }) => {
  await openInline(page);
  const line = page.locator(".cmh-dl-add").first();
  await line.scrollIntoViewIfNeeded();
  await line.hover();
  await expect(page.locator("#diffAddBtn")).toBeVisible();
  await expect.poll(async () => {
    const next = await page.evaluate(() => {
      const lineEl = document.querySelector(".cmh-dl-add");
      const btn = document.getElementById("diffAddBtn");
      const lr = lineEl.getBoundingClientRect();
      const br = btn.getBoundingClientRect();
      return { lineTop: lr.top, lineBottom: lr.bottom, btnCenterY: br.top + br.height / 2 };
    });
    return next.btnCenterY >= next.lineTop - 6 && next.btnCenterY <= next.lineBottom + 6;
  }, { timeout: 10000 }).toBe(true);
});

test("two diff blocks keep their comments separate (diffIndex disambiguation)", async ({ page }) => {
  const two =
    '<pre class="cmh-diff" data-diff-label="a.txt">@@ -1 +1 @@\n-one\n+ONE</pre>\n' +
    '<pre class="cmh-diff" data-diff-label="b.txt">@@ -1 +1 @@\n-two\n+TWO</pre>';
  const tpl = fs.readFileSync(INLINE, "utf8").replace(/<pre class="cmh-diff"[\s\S]*?<\/pre>/, two);
  const doc = path.join(os.tmpdir(), "cmh-2diff-" + Date.now() + ".html");
  fs.writeFileSync(doc, tpl);
  _tempDocs.push(doc); // cleaned by afterEach even if an assertion below fails
  await page.goto(fileUrl(doc));
  await ready(page);
  await expect(page.locator(".cmh-diff-view")).toHaveCount(2);
  // Comment on the added line of the SECOND block (diffIndex 1).
  await addDiffComment(page, '.cmh-diff-view[data-diff-index="1"] .cmh-dl-add', "second block");
  const cid = await page.locator(".cmh-dl-hl").first().getAttribute("data-cid");
  // The highlight is only inside block 1, never block 0.
  await expect(page.locator(`.cmh-diff-view[data-diff-index="1"] .cmh-dl-hl[data-cid="${cid}"]`)).toHaveCount(1);
  await expect(page.locator(`.cmh-diff-view[data-diff-index="0"] .cmh-dl-hl`)).toHaveCount(0);
  fs.unlinkSync(doc);
});

test("a poisoned persisted diff comment does not crash init", async ({ page }) => {
  // A comment with a valid SAFE id but a selector-breaking lineKey must not throw
  // during setupDiffLayer (it should simply fail to highlight).
  await page.addInitScript(() => {
    const key = "commentable-html-demo";
    localStorage.setItem(key, JSON.stringify([
      { id: "cbadbadbad", anchorType: "diff", diffIndex: 0, lineKey: '0"] , x[', note: "poison", createdAt: new Date().toISOString() },
    ]));
  });
  await page.goto(fileUrl(INLINE));
  await ready(page); // if setupDiffLayer threw, __commentableHtmlReady would never be set
  await expect(page.locator(".cmh-diff-view")).toHaveCount(1);
});

test("a diff comment survives a layout toggle THEN a reload (both transitions)", async ({ page }) => {
  await openInline(page);
  await addDiffComment(page, ".cmh-dl-add", "toggle then reload");
  const cid = await page.locator(".cmh-dl-hl").first().getAttribute("data-cid");
  await page.locator(".cmh-diff-toggle").click(); // split (default) -> inline
  await expect(page.locator(".cmh-diff-view")).toHaveClass(/cmh-diff-inline/);
  await expect(page.locator(`.cmh-dl-hl[data-cid="${cid}"]`).first()).toBeVisible();
  await page.reload();
  await ready(page);
  // The persisted layout is inline AND the highlight is still anchored after reload.
  await expect(page.locator(".cmh-diff-view")).toHaveClass(/cmh-diff-inline/);
  await expect(page.locator(`.cmh-dl-hl[data-cid="${cid}"]`).first()).toBeVisible();
});

test("a context-line comment highlights BOTH split sides after reload", async ({ page }) => {
  const doc = docWithDiff("@@ -1,3 +1,3 @@\n ctxline\n-old\n+new", "ctx.txt");
  await page.goto(fileUrl(doc));
  await ready(page);
  await addDiffComment(page, '.cmh-dl-ctx[data-side="old"]', "context comment"); // split by default
  const cid = await page.locator(".cmh-dl-hl").first().getAttribute("data-cid");
  await page.reload();
  await ready(page);
  await expect(page.locator(`.cmh-dl-hl[data-cid="${cid}"][data-side="old"]`)).toHaveCount(1);
  await expect(page.locator(`.cmh-dl-hl[data-cid="${cid}"][data-side="new"]`)).toHaveCount(1);
  fs.unlinkSync(doc);
});

test("a diff with no @@ header numbers its lines from 1", async ({ page }) => {
  const doc = docWithDiff("-old\n+new\n context", "no-hunk.txt");
  await installClipboardCapture(page);
  await page.goto(fileUrl(doc));
  await ready(page);
  await addDiffComment(page, ".cmh-dl-del", "del line check");
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toContain("removed line 1"); // not "removed line 0"
  fs.unlinkSync(doc);
});

test("a data-diff-label with embedded newlines is sanitized to a single Anchor line", async ({ page }) => {
  const doc = docWithDiff("@@ -1 +1 @@\n-old\n+new", "file\nINJECTED");
  await installClipboardCapture(page);
  await page.goto(fileUrl(doc));
  await ready(page);
  await addDiffComment(page, ".cmh-dl-add", "label sanitize");
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  const anchorLine = bundle.split("\n").find((l) => l.startsWith("Anchor: diff"));
  expect(anchorLine).toBeTruthy();
  expect(anchorLine).toContain("INJECTED"); // collapsed onto the same line, not a new line
  fs.unlinkSync(doc);
});

test("Copy all for a diff comment includes the HANDLED_IDS_JSON contract and 'added line N'", async ({ page }) => {
  await openInline(page);
  await installClipboardCapture(page);
  await addDiffComment(page, ".cmh-dl-add", "handled contract");
  const cid = await page.locator(".cmh-dl-hl").first().getAttribute("data-cid");
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toMatch(/Anchor: diff [^\n,]+, added line \d+/);
  const m = bundle.match(/HANDLED_IDS_JSON:\s*(\[.*\])/);
  expect(m).toBeTruthy();
  expect(JSON.parse(m[1])).toContain(cid);
});

test("a `-- a`/`++ a` change at a hunk end before the next hunk is not swallowed as a header", async ({ page }) => {
  // Regression for the git-less lookahead ambiguity: the del/add lines at the end
  // of the first hunk must render as del/add, and the second hunk's own lines too.
  const doc = docWithDiff(
    "@@ -1,2 +1,2 @@\n ctx\n--- a\n@@ -10,2 +10,2 @@\n more\n+++ b", "tricky.c");
  await page.goto(fileUrl(doc));
  await ready(page);
  await expect(page.locator(".cmh-dl-del").filter({ hasText: "- a" })).toHaveCount(1);
  await expect(page.locator(".cmh-dl-add").filter({ hasText: "+ b" })).toHaveCount(1);
  // Neither `--- a` nor `+++ b` was misclassified as a muted file header row.
  await expect(page.locator(".cmh-dl-file")).toHaveCount(0);
  fs.unlinkSync(doc);
});

test("a diff comment survives Save-in-HTML (embeddedComments) + reopen", async ({ page, browser }) => {
  await openInline(page);
  await addDiffComment(page, ".cmh-dl-add", "embedded diff comment");
  const cid = await page.locator(".cmh-dl-hl").first().getAttribute("data-cid");
  const [dl] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnSaveHtml"),
  ]);
  const html = fs.readFileSync(await dl.path(), "utf8");
  const arr = JSON.parse(html.match(/id="embeddedComments">([\s\S]*?)<\/script>/)[1].trim());
  expect(arr.find((c) => c.id === cid && c.anchorType === "diff")).toBeTruthy();
  const saved = path.join(os.tmpdir(), "cmh_diff_embed_" + Date.now() + ".html");
  fs.writeFileSync(saved, html);
  const ctx2 = await browser.newContext();
  const page2 = await ctx2.newPage();
  try {
    await page2.goto(fileUrl(saved));
    await ready(page2);
    await expect(page2.locator(`.cmh-dl-hl[data-cid="${cid}"]`).first()).toBeVisible();
    await expect(page2.locator(`.cm-card[data-cid="${cid}"]`)).toHaveCount(1);
  } finally {
    await ctx2.close();
    fs.unlinkSync(saved);
  }
});

test("a `\\ No newline at end of file` marker does not stagger del/add in split view", async ({ page }) => {
  const doc = docWithDiff(
    "@@ -1 +1 @@\n-old line\n\\ No newline at end of file\n+new line\n\\ No newline at end of file", "eof.txt");
  await page.goto(fileUrl(doc));
  await ready(page);
  await expect(page.locator(".cmh-diff-view")).toHaveClass(/cmh-diff-split/); // side-by-side by default
  // The deletion (old side) and addition (new side) share ONE grid row - their
  // top offsets match - rather than staggering across separate rows.
  // The deletion (old side) and addition (new side) share ONE grid row (aligned tops).
  // Poll so a slow first layout under CI contention cannot flake the measurement.
  await expect.poll(async () => {
    const delTop = await page.locator('.cmh-dl-del[data-side="old"]').first()
      .evaluate((el) => Math.round(el.getBoundingClientRect().top));
    const addTop = await page.locator('.cmh-dl-add[data-side="new"]').first()
      .evaluate((el) => Math.round(el.getBoundingClientRect().top));
    return Math.abs(delTop - addTop);
  }, { timeout: 3000 }).toBeLessThanOrEqual(2);
  // Both `\ No newline` markers render as full-width rows (below the paired change).
  await expect(page.locator(".cmh-dl-full").filter({ hasText: "No newline" })).toHaveCount(2);
});

test("newly-supported languages are syntax-highlighted in diffs (runtime parity)", async ({ page }) => {
  // Each of these languages was previously unknown to the diff highlighter (rendered as plain
  // text); they must now emit token spans, matching the author-time highlighter's coverage.
  const cases = [
    { label: "probe.lua", body: '@@ -1 +1 @@\n-x = 1\n+s = "hi" -- note', com: "-- note" },
    { label: "probe.ps1", body: '@@ -1 +1 @@\n-x = 1\n+$s = "hi" # note', com: "# note" },
    { label: "probe.ex", body: '@@ -1 +1 @@\n-x = 1\n+s = "hi" # note', com: "# note" },
    { label: "probe.css", body: '@@ -1 +1 @@\n-a{}\n+a { color: "x"; /* note */ }', com: "/* note */" },
    { label: "probe.hs", body: '@@ -1 +1 @@\n-x = 1\n+s = "hi" -- note', com: "-- note" },
    { label: "probe.bat", body: "@@ -1 +1 @@\n-echo a\n+rem a note", com: "rem a note" },
    { label: "probe.mm", body: '@@ -1 +1 @@\n-int x;\n+id s = @"hi"; // note', com: "// note" },
    { label: "probe.m", body: '@@ -1 +1 @@\n-int x;\n+id s = @"hi"; // note', com: "// note" },
    { label: "probe.groovy", body: '@@ -1 +1 @@\n-x = 1\n+def s = "hi" // note', com: "// note" },
  ];
  for (const c of cases) {
    const doc = docWithDiff(c.body, c.label);
    await page.goto(fileUrl(doc));
    await ready(page);
    const view = page.locator(".cmh-diff-view").first();
    await expect(view, c.label).toBeVisible();
    // Assert the LANGUAGE-SPECIFIC comment token. A "c"-family fallback for an unknown language
    // cannot produce a --, #, or rem comment, so matching the exact comment proves the right
    // family is wired up (not just that some string/comment span happens to render).
    await expect(view.locator(".cmh-dl-code .cmh-code-com", { hasText: c.com }).first(),
      c.label).toBeVisible();
  }
});

test("diff highlighter colors uppercase SQL and PowerShell keywords (case-insensitive parity)", async ({ page }) => {
  const cases = [
    { label: "probe.sql", body: "@@ -1 +1 @@\n-x\n+SELECT id FROM users", kw: "FROM" },
    { label: "probe.ps1", body: "@@ -1 +1 @@\n-x\n+Function Foo { }", kw: "Function" },
    { label: "probe.bat", body: "@@ -1 +1 @@\n-x\n+IF exist a del a", kw: "IF" },
  ];
  for (const c of cases) {
    const doc = docWithDiff(c.body, c.label);
    await page.goto(fileUrl(doc));
    await ready(page);
    const view = page.locator(".cmh-diff-view").first();
    await expect(view, c.label).toBeVisible();
    // The uppercase keyword must color even though the shared keyword set is lowercase.
    await expect(view.locator(".cmh-dl-code .cmh-code-kw", { hasText: c.kw }).first(),
      c.label).toBeVisible();
  }
});
