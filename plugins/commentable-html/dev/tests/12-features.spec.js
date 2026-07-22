import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import { PYTHON ,
  clickSidebarExport } from "./helpers.js";
import fs from "fs";
import os from "os";
import path from "path";
import {
  openKitchenSink, openInline, openNonPortable, addTextComment, selectText, openComposerFor,
  distinctCids, allCids, currentToast, copiedBundle, markTextForCid, storedComments,
  denyExternalNetwork, installClipboardCapture, readDownload, fileUrl, ready,
  startStaticServer, routeMermaidLocal, stageNonPortable, stageInline, openToolbarMenu, KITCHEN_SINK, SKILL,
  expectNoteFenced,
} from "./helpers.js";

// ---------------------------------------------------------------------------
// Composer + menu lifecycle
// ---------------------------------------------------------------------------
test.describe("composer and menu", () => {
  test("the Cancel button closes the composer without creating a comment", async ({ page }) => {
    await openKitchenSink(page);
    const composer = await openComposerFor(page, "#commentRoot section p");
    await composer.locator("textarea").fill("discard me via Cancel");
    await composer.locator('[data-act="cancel"]').click();
    await expect(composer).toHaveCount(0);
    expect(await distinctCids(page)).toBe(0);
    expect(await storedComments(page)).toEqual([]);
  });

  test("a blank/whitespace note is rejected (composer stays, nothing saved)", async ({ page }) => {
    await openKitchenSink(page);
    const composer = await openComposerFor(page, "#commentRoot section p");
    await composer.locator("textarea").fill("   ");
    await composer.locator('[data-act="save"]').click();
    // The save is a no-op: the composer stays open and no comment is created.
    await expect(composer).toBeVisible();
    expect(await distinctCids(page)).toBe(0);
    await expect(page.locator("#toolbarCount")).toHaveText("0");
  });

  test("the composer can be dragged by its handle", async ({ page }) => {
    await openKitchenSink(page);
    const composer = await openComposerFor(page, "#commentRoot section p");
    const before = await composer.boundingBox();
    const handle = composer.locator(".cm-composer-handle");
    const hb = await handle.boundingBox();
    await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
    await page.mouse.down();
    await page.mouse.move(hb.x + 120, hb.y + 90, { steps: 8 });
    await page.mouse.up();
    const after = await composer.boundingBox();
    expect(Math.abs(after.x - before.x) + Math.abs(after.y - before.y)).toBeGreaterThan(40);
  });

  test("an outside click closes the Add-comment menu", async ({ page }) => {
    await openKitchenSink(page);
    await selectText(page, "#commentRoot section p");
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.mouse.click(3, 3);
    await expect(page.locator("#menuComment")).toBeHidden();
    expect(await distinctCids(page)).toBe(0);
  });

  test("a selection inside a .cm-skip region never pops the menu", async ({ page }) => {
    await openKitchenSink(page);
    const popped = await page.evaluate(() => {
      // Find a .cm-skip region that actually carries selectable text (some cm-skip
      // controls, e.g. sort chevrons, are text-free), then select inside it.
      let tn = null;
      for (const skip of document.querySelectorAll("#commentRoot .cm-skip")) {
        const cand = document.createTreeWalker(skip, NodeFilter.SHOW_TEXT).nextNode();
        if (cand && cand.data.trim().length >= 3) { tn = cand; break; }
      }
      if (!tn) return null;
      const r = document.createRange(); r.setStart(tn, 0); r.setEnd(tn, Math.min(3, tn.data.length));
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      tn.parentElement.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 20, clientY: 20 }));
      return true;
    });
    expect(popped, "found a .cm-skip text node").toBe(true);
    await page.evaluate(() => new Promise((r) => setTimeout(r, 0)));
    await expect(page.locator("#menuComment")).toBeHidden();
    expect(await distinctCids(page)).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Copy-all bundle contract + toasts + clipboard fallback
// ---------------------------------------------------------------------------
test.describe("copy all", () => {
  test("the bundle carries the full documented contract for a text comment", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "please rename this");
    await page.click("#btnCopyAll");
    const b = await copiedBundle(page);
    expect(b).toBeTruthy();
    expect(b).toMatch(/^# .+ review \(1 comment\)\n/);
    expect(b).toContain("Source: ");
    expect(b).toContain("## Comment 1\n");
    expect(b).toMatch(/\nId: cm[a-z0-9]+\n/);
    expect(b).toMatch(/\nOffsets: \[\d+, \d+\]\n/);
    expect(b).toContain("Quoted text:");
    expectNoteFenced(b, "please rename this");
    expect(b).toContain("AGENT INSTRUCTIONS:");
    const cid = (await allCids(page))[0];
    expect(b).toContain('HANDLED_IDS_JSON: ["' + cid + '"]');
    // Copy-all also raises the success toast.
    await expect(page.locator("#toast")).toContainText(/Copied 1 comment\./);
  });

  test("the top toolbar Copy all copies the same bundle (positive path)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "top copy path");
    // With a comment present the panel is open, so use the toolbar menu's Copy all is
    // not needed - btnCopyAllTop stays in the always-visible toolbar row only when the
    // panel is closed; close it first, then click the top Copy all.
    await page.locator("#btnCloseSidebar").click();
    await page.click("#btnCopyAllTop");
    const b = await copiedBundle(page);
    expectNoteFenced(b, "top copy path");
    expect(b).toContain("HANDLED_IDS_JSON: [");
  });

  test("Copy all is disabled with zero comments and re-enabled after a comment exists (CMH-COPY-04, CMH-COPY-07)", async ({ page }) => {
    await openKitchenSink(page);
    const topCopy = page.locator("#btnCopyAllTop");
    await expect(topCopy).toHaveAttribute("aria-disabled", "true");
    await expect(topCopy).toHaveAttribute("title", "No comments to copy");
    await topCopy.focus();
    await expect(page.locator(".cm-tooltip")).toContainText("No comments to copy");
    const emptyToast = await currentToast(page);
    await page.keyboard.press("Enter");
    expect(await currentToast(page)).toBe(emptyToast);
    expect(await copiedBundle(page)).toBeNull();

    await addTextComment(page, "#commentRoot section p", "copy me");
    const sidebarCopy = page.locator("#btnCopyAll");
    await expect(sidebarCopy).toHaveAttribute("aria-disabled", "false");
    expect((await sidebarCopy.getAttribute("title")) || (await sidebarCopy.getAttribute("data-cmh-tip"))).toMatch(/Copy all comments/);

    await page.click("#btnClearAll");
    await page.locator(".cm-modal .danger").click();
    await expect(sidebarCopy).toHaveAttribute("aria-disabled", "true");
    expect((await sidebarCopy.getAttribute("title")) || (await sidebarCopy.getAttribute("data-cmh-tip"))).toBe("No comments to copy");
  });

  test("a code comment emits a fenced block and omits the prose-only context fields", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot pre code", "tighten this loop");
    await page.click("#btnCopyAll");
    const b = await copiedBundle(page);
    expect(b).toMatch(/Pinpoint:.*code/i);
    expect(b).toMatch(/```/);
    // Prose-only sections must not appear for a code comment.
    expect(b).not.toContain("In context:");
    expect(b).not.toMatch(/Containing <(pre|block)>/);
  });

  test("Copy all falls back to execCommand when the async clipboard is unavailable", async ({ page }) => {
    await page.addInitScript(() => {
      // Force the async clipboard path to fail, and record the execCommand fallback.
      try { Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("blocked")) }, configurable: true }); } catch (e) {}
      window.__execCopied = [];
      document.execCommand = (cmd) => {
        if (cmd === "copy") {
          const ta = document.querySelector("textarea[style*='-9999px']");
          window.__execCopied.push(ta ? ta.value : "");
          return true;
        }
        return false;
      };
    });
    await page.goto(fileUrl(KITCHEN_SINK));
    await ready(page);
    await addTextComment(page, "#commentRoot section p", "fallback copy");
    await page.click("#btnCopyAll");
    const execd = await page.evaluate(() => window.__execCopied);
    expect(execd.length).toBe(1);
    expectNoteFenced(execd[0], "fallback copy");
    await expect(page.locator("#toast")).toContainText(/Copied 1 comment\./);
  });

  test("Copy all falls back to prompt() when both clipboard paths fail", async ({ page }) => {
    await page.addInitScript(() => {
      try { Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("blocked")) }, configurable: true }); } catch (e) {}
      window.__execAttempts = [];
      document.execCommand = (cmd) => {
        if (cmd === "copy") {
          const ta = document.querySelector("textarea[style*='-9999px']");
          window.__execAttempts.push(ta ? ta.value : "");
        }
        return false; // execCommand copy also fails -> forces the prompt() last resort
      };
      window.__prompted = [];
      window.prompt = (msg, val) => { window.__prompted.push(val); return null; };
    });
    await page.goto(fileUrl(KITCHEN_SINK));
    await ready(page);
    await addTextComment(page, "#commentRoot section p", "prompt fallback");
    await page.click("#btnCopyAll");
    // The order is proven: async clipboard failed -> execCommand("copy") was attempted
    // (with the full bundle) and returned false -> prompt() got the same bundle.
    const exec = await page.evaluate(() => window.__execAttempts);
    const prompted = await page.evaluate(() => window.__prompted);
    expect(exec.length).toBe(1);
    expect(exec[0]).toContain("prompt fallback");
    expect(exec[0]).toContain("HANDLED_IDS_JSON: [");
    expect(prompted.length).toBe(1);
    expectNoteFenced(prompted[0], "prompt fallback");
    expect(prompted[0]).toContain("HANDLED_IDS_JSON: [");
  });

  test("a comment under headings surfaces Where / Pinpoint / In context metadata", async ({ page }) => {
    await openKitchenSink(page);
    // #dup-b is the SECOND occurrence of a repeated sentence, nested under H1 > H2.
    await addTextComment(page, "#dup-b", "which occurrence?");
    await page.click("#btnCopyAll");
    const b = await copiedBundle(page);
    expect(b).toMatch(/\nWhere: H1 /);              // heading path captured
    expect(b).toMatch(/\nPinpoint: .*match 2 of 2/); // occurrence disambiguation
    expect(b).toContain("In context:");             // surrounding prose context
  });
});
test.describe("highlight interactions", () => {
  test("the hover bubble appears on a plain (non-link) highlight and opens its comment", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "bubble on a plain mark");
    const cid = (await allCids(page))[0];
    const mark = page.locator(`mark.cm-hl[data-cid="${cid}"]`).first();
    await mark.scrollIntoViewIfNeeded();
    await mark.hover();
    await expect(page.locator("#hlBubble")).toBeVisible();
    await page.locator("#hlBubble").click();
    expect(await page.evaluate(() => document.body.classList.contains("sidebar-open"))).toBe(true);
    await expect(page.locator(`.cm-card[data-cid="${cid}"]`)).toHaveClass(/active/);
  });

  test("clicking a specific highlight activates that comment's card (cid-mapped)", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "first", 0);
    await addTextComment(page, "#commentRoot section p", "second", 1);
    const cids = await allCids(page);
    expect(cids.length).toBe(2);
    const target = cids[1];
    await page.locator(`mark.cm-hl[data-cid="${target}"]`).first().click();
    await expect(page.locator(`.cm-card[data-cid="${target}"]`)).toHaveClass(/active/);
    await expect(page.locator(`.cm-card[data-cid="${cids[0]}"]`)).not.toHaveClass(/active/);
  });
});

// ---------------------------------------------------------------------------
// Rejection / error toasts
// ---------------------------------------------------------------------------
test.describe("rejection paths", () => {
  test("an overlapping selection never corrupts the existing comment", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "first comment here");
    const firstCid = (await allCids(page))[0];
    const firstText = await markTextForCid(page, firstCid);
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    // Select a range that overlaps the existing mark and try to comment it. The layer
    // now REJECTS it (overlap toast, composer stays open) rather than nesting a mark
    // (CMH-CORE-11); the CONTRACT is: the original comment is never lost or corrupted,
    // and no mark is nested inside another.
    const opened = await page.evaluate(() => {
      const mark = document.querySelector("#commentRoot mark.cm-hl");
      const p = mark.closest("p") || mark.parentElement;
      p.scrollIntoView({ block: "center" });
      const r = document.createRange();
      r.selectNodeContents(p);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      if (!s.toString().trim()) return false;
      p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 30, clientY: 30 }));
      return true;
    });
    expect(opened).toBe(true);
    await page.evaluate(() => new Promise((r) => setTimeout(r, 0))); // drain the mouseup setTimeout(0)
    // The whole-paragraph selection overlaps the existing mark, so the menu MUST appear; assert
    // it unconditionally so a menu regression fails here instead of silently skipping the check.
    const menu = page.locator("#menuComment");
    await expect(menu).toBeVisible();
    await menu.click();
    const composer = page.locator(".cm-composer").last();
    await composer.scrollIntoViewIfNeeded();
    await composer.locator("textarea").fill("overlapping");
    await composer.locator('[data-act="save"]').click();
    // Rejected: the not-saved toast shows and the composer stays open (no new comment).
    expect(await currentToast(page)).toContain("Comment was not saved");
    await composer.locator('[data-act="cancel"]').click();
    await expect(composer).toHaveCount(0);
    // Contract: no page error; the ORIGINAL comment survives with its exact text;
    // DOM cids == cards == storage; no mark is nested inside another mark.
    expect(errors).toEqual([]);
    expect(await storedComments(page).then((c) => c.some((x) => x.id === firstCid))).toBe(true);
    expect(await markTextForCid(page, firstCid)).toBe(firstText);
    const stored = (await storedComments(page)).length;
    expect(await distinctCids(page)).toBe(stored);
    expect(await page.locator(".cm-card").count()).toBe(stored);
    const nested = await page.evaluate(() =>
      [...document.querySelectorAll("mark.cm-hl mark.cm-hl")].length);
    expect(nested, "no mark nested inside another mark").toBe(0);
  });

  // CMH-CORE-11: two composers opened on the SAME (or overlapping) text before either
  // saves must not both anchor - wrapping the second range inside the first produces a
  // nested `<mark class="cm-hl" data-cid=A><mark class="cm-hl" data-cid=B>` whose outer
  // highlight becomes unclickable. The second save is rejected with the not-saved toast
  // and creates no comment; editing the existing comment on the same range (CMH-CORE-10)
  // still works because that path never re-wraps.
  test("two composers on the same range: the second is rejected, not nested (CMH-CORE-11)", async ({ page }) => {
    await openKitchenSink(page);
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    // Open two composers on the identical selection BEFORE either is saved, so the
    // second is a genuine new-comment save (not a CMH-CORE-10 reopen of a saved one).
    const openContentsComposer = async () => {
      await page.evaluate(() => {
        const p = document.querySelector("#commentRoot section p");
        p.scrollIntoView({ block: "center" });
        const r = document.createRange();
        r.selectNodeContents(p);
        const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
        p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 30, clientY: 30 }));
      });
      await expect(page.locator("#menuComment")).toBeVisible();
      await page.locator("#menuComment").click();
    };
    await openContentsComposer();
    await openContentsComposer();
    const composers = page.locator(".cm-composer");
    await expect(composers).toHaveCount(2);

    // Save the first: it anchors and creates exactly one comment/highlight.
    await composers.nth(0).locator("textarea").fill("first note");
    await composers.nth(0).locator('[data-act="save"]').click();
    await expect(composers).toHaveCount(1);
    expect(await storedComments(page)).toHaveLength(1);
    const firstCid = (await allCids(page))[0];

    // Save the second on the identical range: rejected with the not-saved toast, no
    // second comment, and NO nested mark of a different cid inside the first.
    await composers.nth(0).locator("textarea").fill("second note");
    await composers.nth(0).locator('[data-act="save"]').click();
    expect(await currentToast(page)).toContain("Comment was not saved");
    expect(await storedComments(page)).toHaveLength(1);
    expect(await distinctCids(page)).toBe(1);
    const nested = await page.evaluate(() =>
      [...document.querySelectorAll("mark.cm-hl mark.cm-hl")].length);
    expect(nested, "no cm-hl nested inside another cm-hl").toBe(0);
    expect(errors).toEqual([]);

    // The rejected composer stays open (the user can adjust the selection); close it.
    await page.locator(".cm-composer").last().locator('[data-act="cancel"]').click();
    await expect(page.locator(".cm-composer")).toHaveCount(0);

    // CMH-CORE-10 still works: selecting the same range reopens the existing comment for
    // editing (prefilled), and editing does not create a duplicate or a nested mark.
    await page.evaluate(() => {
      const p = document.querySelector("#commentRoot section p");
      const r = document.createRange();
      r.selectNodeContents(p);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 30, clientY: 30 }));
    });
    await expect(page.locator("#menuComment")).toBeVisible();
    await page.locator("#menuComment").click();
    const editComposer = page.locator(".cm-composer").last();
    await expect(editComposer.locator("textarea")).toHaveValue("first note");
    await editComposer.locator("textarea").fill("edited note");
    await editComposer.locator('[data-act="save"]').click();
    await expect(editComposer).toHaveCount(0);
    expect(await storedComments(page)).toHaveLength(1);
    expect((await allCids(page))[0]).toBe(firstCid);
    expect(await page.locator(".cm-card").filter({ hasText: "edited note" }).count()).toBe(1);
  });

  // CMH-CORE-11: a crafted / legacy persisted set can contain overlapping text comments (the
  // composer can no longer create them). restoreHighlights must apply them defensively - keep
  // only the FIRST-by-start highlight, never nest a mark.cm-hl inside another - while both
  // comments stay LISTED in the sidebar (mirroring the diff sub-range apply-time guard).
  test("startup keeps only the first of two overlapping persisted comments, never nesting (CMH-CORE-11)", async ({ page }) => {
    await openKitchenSink(page);
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await addTextComment(page, "#commentRoot section p", "first note");
    const first = (await storedComments(page))[0];
    expect(Number.isFinite(first.start) && first.end - first.start >= 2).toBe(true);

    // Inject a second text comment whose range is CONTAINED in the first (a genuine overlap
    // that would nest), as a hand-crafted / legacy localStorage array would, then reload so
    // restoreHighlights runs its sweep.
    await page.evaluate((f) => {
      const arr = window.__cmhStorageCodec.read();
      arr.push({ ...f, id: "coverlap01", start: f.start + 1, end: f.end, note: "second overlapping" });
      window.__cmhStorageCodec.write(arr);
    }, first);
    await page.reload();
    await ready(page);

    // Both comments stay listed; only the first (by start) is highlighted; no nested marks.
    expect(await storedComments(page)).toHaveLength(2);
    expect(await page.locator(".cm-card").count()).toBe(2);
    expect(await distinctCids(page)).toBe(1);
    expect((await allCids(page))[0]).toBe(first.id);
    expect(await markTextForCid(page, "coverlap01")).toBe("");
    const nested = await page.evaluate(() =>
      [...document.querySelectorAll("mark.cm-hl mark.cm-hl")].length);
    expect(nested, "no mark nested inside another mark on restore").toBe(0);
    expect(errors).toEqual([]);
  });

  // CMH-CORE-11: a selection that merely ABUTS an existing highlight (its start equals the
  // highlight's end, sharing zero characters) is NOT an overlap and must save. The overlap guard
  // derives each highlight's live character interval and uses a half-open test, so touching edges
  // are allowed; a boundary-only DOM comparison would wrongly reject this.
  test("a selection abutting an existing highlight is allowed, not rejected as overlap (CMH-CORE-11)", async ({ page }) => {
    await openInline(page);
    const phrase = "character offsets";
    // Global character offset of the phrase within #commentRoot (skipping cm-skip), the same
    // offset space the runtime anchors in.
    const g = await page.evaluate((ph) => {
      const root = document.getElementById("commentRoot");
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode(n) {
          return n.parentElement && n.parentElement.closest(".cm-skip")
            ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
        },
      });
      let acc = "", n;
      while ((n = walker.nextNode())) acc += n.data;
      return acc.indexOf(ph);
    }, phrase);
    expect(g).toBeGreaterThanOrEqual(0);

    const commentOffsets = async (s, e, note) => {
      await page.evaluate(({ s, e }) => {
        const root = document.getElementById("commentRoot");
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
          acceptNode(n) {
            return n.parentElement && n.parentElement.closest(".cm-skip")
              ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
          },
        });
        let acc = 0, sn = null, so = 0, en = null, eo = 0, n;
        while ((n = walker.nextNode())) {
          const len = n.data.length;
          if (sn === null && s >= acc && s <= acc + len) { sn = n; so = s - acc; }
          if (en === null && e >= acc && e <= acc + len) { en = n; eo = e - acc; }
          acc += len;
        }
        const r = document.createRange();
        r.setStart(sn, so); r.setEnd(en, eo);
        const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
        root.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 40, clientY: 40 }));
      }, { s, e });
      await expect(page.locator("#menuComment")).toBeVisible();
      await page.locator("#menuComment").click();
      const c = page.locator(".cm-composer").last();
      await c.locator("textarea").fill(note);
      await c.locator('[data-act="save"]').click();
      await expect(c).toHaveCount(0);
    };

    const mid = g + Math.floor(phrase.length / 2);
    await commentOffsets(g, mid, "first half");             // highlight A covers [g, mid)
    await commentOffsets(mid, g + phrase.length, "abutting"); // [mid, ...) abuts A - must save
    expect(await distinctCids(page)).toBe(2);                 // both saved
    expect(await storedComments(page)).toHaveLength(2);
    const nested = await page.evaluate(() =>
      [...document.querySelectorAll("mark.cm-hl mark.cm-hl")].length);
    expect(nested, "abutting highlights are siblings, never nested").toBe(0);
  });

  test("a cross-structural selection either anchors exactly or is cleanly rejected with a toast", async ({ page }) => {
    await openKitchenSink(page);
    // Select from inside one table cell across to another - a structural boundary.
    const info = await page.evaluate(() => {
      const cells = [...document.querySelectorAll("#commentRoot table td")];
      if (cells.length < 2) return { ok: false };
      const a = document.createTreeWalker(cells[0], NodeFilter.SHOW_TEXT).nextNode();
      const b = document.createTreeWalker(cells[cells.length - 1], NodeFilter.SHOW_TEXT).nextNode();
      if (!a || !b) return { ok: false };
      cells[0].scrollIntoView({ block: "center" });
      const r = document.createRange();
      r.setStart(a, 0); r.setEnd(b, b.data.length);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      const live = s.rangeCount ? s.getRangeAt(0) : r;
      // Expected covered text = the range's text nodes concatenated (no cell
      // separators), which is exactly what the wrapped marks contain.
      const expected = live.cloneContents().textContent;
      cells[0].dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 30, clientY: 30 }));
      return { ok: true, expected };
    });
    expect(info.ok).toBe(true);
    await page.evaluate(() => new Promise((r) => setTimeout(r, 0))); // drain the mouseup setTimeout(0)
    const menu = page.locator("#menuComment");
    if (!(await menu.isVisible().catch(() => false))) {
      // A non-empty in-root selection MUST pop the menu; a silent no-op would be a
      // contract violation. (Only an empty/whitespace selection may skip the menu.)
      expect(info.expected.trim(), "a non-empty cross-structural selection must pop the menu").toBe("");
      expect(await distinctCids(page)).toBe(0);
      expect(await storedComments(page)).toEqual([]);
      return;
    }
    await menu.click();
    const composer = page.locator(".cm-composer").last();
    if (await composer.count() === 0) {
      // offsetWithin rejected the boundary: a toast fired and no composer/comment.
      await expect(page.locator("#toast")).toContainText(/Could not anchor that selection/);
      expect(await distinctCids(page)).toBe(0);
      expect(await storedComments(page)).toEqual([]);
      return;
    }
    // Otherwise it anchored: the highlight covers EXACTLY the selected DOM text.
    await composer.scrollIntoViewIfNeeded();
    await composer.locator("textarea").fill("cross-cell");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    expect(await distinctCids(page)).toBe(1);
    const cid = (await allCids(page))[0];
    expect(await markTextForCid(page, cid)).toBe(info.expected);
  });

  test("a comment whose stored text no longer exists degrades gracefully on reload", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "will lose its anchor");
    // Corrupt the stored offsets so restore-from-offsets cannot re-anchor.
    await page.evaluate(() => {
      const arr = window.__cmhStorageCodec.read();
      arr[0].start = 99999999; arr[0].end = 99999999 + 5;
      window.__cmhStorageCodec.write(arr);
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.reload();
    await ready(page);
    // The card still shows (comment not silently dropped), no page crash, no orphan mark.
    await expect(page.locator(".cm-card")).toHaveCount(1);
    expect(errors).toEqual([]);
    expect(await distinctCids(page)).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Exports preserve the current comments; filenames follow the contract
// ---------------------------------------------------------------------------
test.describe("exports preserve comments", () => {
  test("Save comments embeds the comment and downloads <stem>-portable.html", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "save me into the file");
    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    expect(dl.suggestedFilename()).toMatch(/-portable\.html$/);
    const html = await readDownload(dl);
    expect(html).toContain("save me into the file");
    await expect(page.locator("#toast")).toContainText(/Downloaded/);
  });

  test("the top toolbar Save comments button also embeds and downloads", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "top save note");
    await page.locator("#btnCloseSidebar").click(); // close panel so the toolbar shows
    await openToolbarMenu(page); // Save comments (top) lives in the overflow menu
    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSaveHtmlTop"),
    ]);
    expect(dl.suggestedFilename()).toMatch(/-portable\.html$/);
    expect(await readDownload(dl)).toContain("top save note");
  });

  test("Export with embedded comments makes a portable standalone file from an nonportable doc and reopens showing them", async ({ page, context }) => {
    // Over file:// _getBaseHtml() uses the in-memory snapshot (no fetch), so this has
    // no http-server dependency; the HTTP export path is covered by 11-coverage.
    let dir;
    try {
      const staged = stageNonPortable();
      dir = staged.dir;
      await installClipboardCapture(page);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addTextComment(page, "#commentRoot section p", "travels in the standalone");
      // A comment is present so the panel is open: the sidebar "Export with embedded
      // comments" always yields a portable combined file, even from an nonportable doc.
      const [dl] = await Promise.all([
        page.waitForEvent("download"),
        clickSidebarExport(page, "#btnSaveHtml"),
      ]);
      expect(dl.suggestedFilename()).toMatch(/-portable\.html$/);
      const html = await readDownload(dl);
      const tmp = path.join(os.tmpdir(), "cmh_std_comments_" + Date.now() + ".html");
      fs.writeFileSync(tmp, html);
      let p2;
      try {
        // Re-opening the exported file in a fresh browser (no localStorage) proves it
        // is a valid inline document that carries its comments.
        p2 = await context.newPage();
        await p2.goto(fileUrl(tmp));
        await ready(p2);
        await expect(p2.locator("#commentList")).toContainText("travels in the standalone");
        expect(await p2.evaluate(() => document.body.classList.contains("cm-nonportable"))).toBe(false);
      } finally {
        if (p2) await p2.close();
        fs.rmSync(tmp, { force: true });
      }
    } finally {
      if (dir) fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("Export plain unwraps highlights, drops sidebar-open, keeps content, and leaves localStorage intact", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot section p", "note that must not leak");
    // Adding a comment already opened the panel (body.sidebar-open), which the plain
    // export must strip. Save from the sidebar's Export plain.
    const keyBefore = await page.evaluate(() => {
      const k = document.getElementById("commentRoot").dataset.commentKey;
      return localStorage.getItem(k + "::z");
    });
    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSavePlain"),
    ]);
    expect(dl.suggestedFilename()).toMatch(/\.plain\.html$/);
    const html = await readDownload(dl);
    expect(html).not.toMatch(/<mark class="cm-hl"/);
    expect(html).not.toContain("note that must not leak");
    expect(html).not.toMatch(/<body[^>]*class="[^"]*sidebar-open/);
    expect(html).toContain("Kitchen-sink sample");
    // The open document's own storage is untouched by exporting.
    const keyAfter = await page.evaluate(() => {
      const k = document.getElementById("commentRoot").dataset.commentKey;
      return localStorage.getItem(k + "::z");
    });
    expect(keyAfter).toBe(keyBefore);
  });
});

// ---------------------------------------------------------------------------
// Mermaid copy payload + ring click (served over http so mermaid renders)
// ---------------------------------------------------------------------------
test.describe("mermaid copy + activation", () => {
  async function openMermaid(page) {
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/dist/PORTABLE.html?mermaid=1");
      await ready(page);
    } catch (e) {
      await server.close();
      throw e;
    }
    return server;
  }

  test("a mermaid comment produces a mermaid Copy-all payload and its ring activates the card", async ({ page }) => {
    const server = await openMermaid(page);
    try {
      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });
      const label = (await node.textContent()).trim();
      await node.hover();
      await page.locator("#mermaidAddBtn").click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("rename this node");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);

      // Copy-all payload uses the mermaid shape (no Offsets/Quoted text).
      await page.click("#btnCopyAll");
      const b = await copiedBundle(page);
      expect(b).toContain("## Comment 1 (mermaid)");
      expect(b).toMatch(/Anchor: mermaid diagram #1, node "/);
      expectNoteFenced(b, "rename this node");
      expect(b).not.toContain("Offsets: [");
      expect(b).not.toContain("Quoted text:");

      // Clicking the ring opens the sidebar and activates the card.
      const cid = (await page.locator(".cm-card").first().getAttribute("data-cid"));
      await page.locator(`#commentRoot .mermaid .cm-mermaid-hl[data-cid="${cid}"]`).click();
      expect(await page.evaluate(() => document.body.classList.contains("sidebar-open"))).toBe(true);
      await expect(page.locator(`.cm-card[data-cid="${cid}"]`)).toHaveClass(/active/);
      expect(label.length).toBeGreaterThan(0);
    } finally {
      await server.close();
    }
  });

  test("a mermaid card's jump action scrolls to and rings the node", async ({ page }) => {
    const server = await openMermaid(page);
    try {
      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });
      await node.hover();
      await page.locator("#mermaidAddBtn").click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("jump to this node");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);
      const cid = await page.locator(".cm-card").first().getAttribute("data-cid");
      // Scroll away, then use the card's jump action to return to the node.
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await page.locator(`.cm-card[data-cid="${cid}"] [data-act="jump"]`).click();
      const ring = page.locator(`#commentRoot .mermaid .cm-mermaid-hl[data-cid="${cid}"]`);
      await expect(ring).toBeVisible();
      await expect.poll(async () =>
        ring.evaluate((el) => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.top <= window.innerHeight; })).toBe(true);
    } finally {
      await server.close();
    }
  });

  test("a handled mermaid comment is excluded from Copy all after reload", async ({ page }) => {
    let server, dir;
    try {
      const staged = stageInline();
      dir = staged.dir;
      server = await startStaticServer(dir);
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/" + path.basename(staged.html) + "?mermaid=1");
      await ready(page);
      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });
      await node.hover();
      await page.locator("#mermaidAddBtn").click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("handled mermaid note");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);
      const cid = await page.locator(".cm-card").first().getAttribute("data-cid");
      execFileSync(PYTHON, ["tools/authoring/mark_handled.py", staged.html, cid], { cwd: SKILL });
      await page.reload();
      await ready(page);
      await expect(page.locator("#commentRoot .mermaid svg g.node").first()).toBeVisible({ timeout: 20000 });
      // 0 live comments after prune -> the toolbar Copy all stays focusable but aria-disabled.
      await expect(page.locator("#btnCopyAllTop")).toHaveAttribute("aria-disabled", "true");
      await page.locator("#btnCopyAllTop").focus();
      const pruneToast = await currentToast(page);
      await page.keyboard.press("Enter");
      expect(await currentToast(page)).toBe(pruneToast);
      expect(await copiedBundle(page)).toBeNull();
    } finally {
      if (server) await server.close();
      if (dir) fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------
// Self-contained guarantee
// ---------------------------------------------------------------------------
test.describe("self-contained guarantee", () => {
  test("a normal inline document stays functional when external requests are denied", async ({ page }) => {
    // mermaid's CDN import is the ONE deliberate online dependency; strip its loader so
    // this exercises the layer with denied remote requests (denyExternalNetwork aborts
    // and records every non-local request, including the mermaid CDN).
    const { html, dir } = stageInline({
      mutate: (h) => h.replace(/<script type="module">[\s\S]*?jsdelivr[\s\S]*?<\/script>/gi, ""),
    });
    try {
      await denyExternalNetwork(page);
      await installClipboardCapture(page);
      await page.goto(fileUrl(html));
      await ready(page);
      await addTextComment(page, "#commentRoot p", "self-contained works");
      expect(page.__external, "unexpected external requests: " + JSON.stringify(page.__external)).toEqual([]);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
