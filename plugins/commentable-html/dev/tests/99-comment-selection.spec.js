// Per-comment selection in the side pane: pick individual comment threads and hand back (or
// delete) only those, instead of the all-or-nothing Copy all / Clear all. Also covers the card's
// unified action row, where jump/edit/delete share the Reply button's row and look.
import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  openInline, addTextComment, installClipboardCapture, ready, fileUrl, stageContent,
  lastCopied, machineTrailerBody, storedComments, openSidebarMoreMenu, openSearch,
  clickClearAll, clickSidebarExport, readDownload,
} from "./helpers.js";

const CARD = "#commentList .cm-card";
const PICK = "input.cm-pick-box";

// A document whose prose can carry several distinct comments AND that owns an editable note, a
// review checklist, and a movable widget board, so the "a selection is a comment-only scope" rule
// has a tracked non-comment change of EVERY kind to exclude.
const DOC = `
  <h1>Selection demo</h1>
  <p id="pa">Alpha paragraph for the first comment.</p>
  <p id="pb">Beta paragraph for the second comment.</p>
  <p id="pc">Gamma paragraph for the third comment.</p>
  <div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Reviewer risk summary">No blocking risks yet.</div>
  <div class="cmh-checklist" data-cmh-checklist="readiness" data-cmh-checklist-label="Review readiness">
    <ul>
      <li data-cmh-item="signoff" data-cmh-state="blank">Sign-off collected</li>
    </ul>
  </div>
  <div class="board cm-skip" data-cm-widget="triage" id="board">
    <div class="col" data-cm-slot="Now" id="now">
      <div class="card" data-cm-part="a" data-cm-part-label="Card A">Card A</div>
    </div>
    <div class="col" data-cm-slot="Later" id="later">
      <div class="card" data-cm-part="b" data-cm-part-label="Card B">Card B</div>
    </div>
  </div>`;

const staged = [];
test.afterEach(() => {
  while (staged.length) {
    const dir = staged.pop();
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) { /* best effort */ }
  }
});

async function openDoc(page) {
  const s = stageContent(DOC, { key: "cmh-pick-doc", source: "pick-doc.html" });
  staged.push(s.dir);
  await installClipboardCapture(page);
  await page.goto(fileUrl(s.html));
  await ready(page);
}

// Seed three comments, one per paragraph, and return their ids in card order.
async function seedThree(page) {
  await openDoc(page);
  await addTextComment(page, "#pa", "alpha note");
  await addTextComment(page, "#pb", "beta note");
  await addTextComment(page, "#pc", "gamma note");
  await expect(page.locator(CARD)).toHaveCount(3);
  return page.$$eval(CARD, (els) => els.map((el) => el.dataset.cid));
}

function card(page, cid) { return page.locator(`${CARD}[data-cid="${cid}"]`); }

async function pick(page, cid) {
  await card(page, cid).locator(PICK).check();
  await expect(card(page, cid).locator(PICK)).toBeChecked();
}

// Reply to one comment card, so a selected thread has something to drag along with it.
async function addReply(page, cid, note) {
  await card(page, cid).locator(".cm-reply-btn").click();
  const composer = card(page, cid).locator(".cm-reply-compose");
  await composer.locator("textarea").fill(note);
  await composer.locator(".cm-reply-save").click();
  await expect(composer).toHaveCount(0);
}

// Move a board card between slots, the way a drag/drop does, so a widget-layout change is tracked.
async function moveBoardCard(page, part, targetSlotId) {
  await page.evaluate(({ part, targetSlotId }) => {
    document.getElementById(targetSlotId).appendChild(document.querySelector('[data-cm-part="' + part + '"]'));
  }, { part, targetSlotId });
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
}

test.describe("side-pane comment selection", () => {
  test("every comment card carries a Select control that picks that thread (CMH-PICK-01)", async ({ page }) => {
    const ids = await seedThree(page);
    // One obvious, keyboard-reachable, accessibly-named control per card.
    await expect(page.locator(`${CARD} ${PICK}`)).toHaveCount(3);
    const box = card(page, ids[1]).locator(PICK);
    await expect(box).not.toBeChecked();
    // The name identifies WHICH comment it picks, not a bare "Select" repeated on every card.
    await expect(box).toHaveAttribute("aria-label", /^Select comment #\d+$/);

    await box.check();
    await expect(box).toBeChecked();
    await expect(card(page, ids[1])).toHaveClass(/cm-card-picked/);
    // Picking one card leaves the others alone.
    await expect(card(page, ids[0]).locator(PICK)).not.toBeChecked();
    await expect(card(page, ids[0])).not.toHaveClass(/cm-card-picked/);

    // ...and it is a TOGGLE: unchecking gives the selection back.
    await box.uncheck();
    await expect(box).not.toBeChecked();
    await expect(card(page, ids[1])).not.toHaveClass(/cm-card-picked/);
    await expect(page.locator("#cmSelectBar")).toBeHidden();

    // Only thread ROOTS are pickable: a thread travels together, so a reply has no control of its
    // own that could put half a thread in the selection.
    await addReply(page, ids[0], "alpha refinement");
    await expect(page.locator(`${CARD} .cm-reply`)).toHaveCount(1);
    await expect(page.locator(`${CARD} .cm-reply ${PICK}`)).toHaveCount(0);
    await expect(page.locator(`${CARD} ${PICK}`)).toHaveCount(3);
  });

  test("picking and clearing never re-render the list, so an open draft survives (CMH-PICK-01, CMH-PICK-05)", async ({ page }) => {
    const ids = await seedThree(page);
    // A dirty inline reply draft on one card. Toggling a pick on ANOTHER card must not rebuild the
    // list: a re-render replaces the whole DOM, and the draft only survives it through the separate
    // CMH-THREAD-09 machinery - which is not what these rows promise.
    await card(page, ids[0]).locator(".cm-reply-btn").click();
    const composer = card(page, ids[0]).locator(".cm-reply-compose");
    await composer.locator("textarea").fill("draft in progress");
    // Tag the live composer node so a rebuilt replacement is detectable even if its text is restored.
    await composer.evaluate((el) => { el.dataset.cmhProbe = "same-node"; });

    await card(page, ids[1]).locator(PICK).check();
    await expect(page.locator("#cmSelectCount")).toHaveText(/1 comment selected/);
    await expect(composer).toHaveAttribute("data-cmh-probe", "same-node");
    await expect(composer.locator("textarea")).toHaveValue("draft in progress");

    await page.locator("#btnClearSelection").click();
    await expect(page.locator("#cmSelectBar")).toBeHidden();
    await expect(composer).toHaveAttribute("data-cmh-probe", "same-node");
    await expect(composer.locator("textarea")).toHaveValue("draft in progress");
  });

  test("a selection relabels the copy control to Copy selected and counts itself (CMH-PICK-02)", async ({ page }) => {
    const ids = await seedThree(page);
    const copy = page.locator("#btnCopyAll");
    await expect(copy).toHaveText(/Copy all/);
    await expect(page.locator("#cmSelectBar")).toBeHidden();

    await pick(page, ids[0]);
    await expect(copy).toHaveText(/Copy selected/);
    await expect(page.locator("#btnCopyAllTop")).toHaveText(/Copy selected/);
    await expect(page.locator("#cmSelectBar")).toBeVisible();
    await expect(page.locator("#cmSelectCount")).toHaveText(/1 comment selected/);
    // The count rides in the tooltip of BOTH controls: the sidebar primary and the floating
    // toolbar's twin, which is the only one a reviewer sees while the panel is collapsed.
    await expect(copy).toHaveAttribute("title", /the 1 selected comment\b/);
    await expect(page.locator("#btnCopyAllTop")).toHaveAttribute("title", /the 1 selected comment\b/);

    await pick(page, ids[2]);
    await expect(page.locator("#cmSelectCount")).toHaveText(/2 comments selected/);
    await expect(copy).toHaveAttribute("title", /the 2 selected comments\b/);
    await expect(page.locator("#btnCopyAllTop")).toHaveAttribute("title", /the 2 selected comments\b/);

    // Dropping back to an empty selection restores the all-or-nothing default, tooltips included.
    await card(page, ids[0]).locator(PICK).uncheck();
    await card(page, ids[2]).locator(PICK).uncheck();
    await expect(copy).toHaveText(/Copy all/);
    await expect(page.locator("#btnCopyAllTop")).toHaveText(/Copy all/);
    await expect(copy).toHaveAttribute("title", /Copy all comments/);
    await expect(page.locator("#btnCopyAllTop")).toHaveAttribute("title", /Copy all comments/);
    await expect(page.locator("#cmSelectBar")).toBeHidden();
  });

  test("the live count is written only when it actually changes (CMH-PICK-02)", async ({ page }) => {
    const ids = await seedThree(page);
    await pick(page, ids[0]);
    await expect(page.locator("#cmSelectCount")).toHaveText(/1 comment selected/);
    // #cmSelectCount is an aria-live region and the panel re-renders for reasons that have nothing
    // to do with the selection (a sort, a checklist tick, a note keystroke). Re-writing an
    // UNCHANGED count would re-announce it to a screen reader while the reviewer is elsewhere.
    const writes = await page.evaluate(async () => {
      const el = document.getElementById("cmSelectCount");
      let n = 0;
      const obs = new MutationObserver((records) => { n += records.length; });
      obs.observe(el, { childList: true, characterData: true, subtree: true });
      document.getElementById("btnSort").click();   // a full re-render, selection untouched
      document.getElementById("btnSort").click();
      await new Promise((r) => setTimeout(r, 50));
      obs.disconnect();
      return n;
    });
    expect(writes, "an unchanged count is not re-announced").toBe(0);
    await expect(page.locator("#cmSelectCount")).toHaveText(/1 comment selected/);
  });

  test("Copy selected emits only the selected threads, replies included (CMH-PICK-03)", async ({ page }) => {
    const ids = await seedThree(page);
    // Give the first comment a reply, so the thread-travels-together rule is exercised.
    await addReply(page, ids[0], "alpha refinement");

    await pick(page, ids[0]);
    await page.locator("#btnCopyAll").click();
    const bundle = await lastCopied(page);
    expect(bundle, "the bundle reached the clipboard").toBeTruthy();
    expect(bundle).toContain("alpha note");
    expect(bundle).toContain("alpha refinement");
    expect(bundle, "an unselected comment is not handed back").not.toContain("beta note");
    expect(bundle).not.toContain("gamma note");
    expect(bundle).toMatch(/^# .* review \(1 comment\)$/m);

    // The handled-id contract only names what was actually copied, so the agent can never mark an
    // unselected comment handled and prune it out from under the reviewer.
    const trailer = machineTrailerBody(bundle);
    const handled = JSON.parse(/HANDLED_IDS_JSON: (.*)/.exec(trailer)[1]);
    expect(handled).toContain(ids[0]);
    expect(handled).not.toContain(ids[1]);
    expect(handled).not.toContain(ids[2]);
    expect(handled.length, "the root plus its one reply").toBe(2);
  });

  test("a partial hand-back declares its scope and carries no tracked note change (CMH-PICK-04)", async ({ page }) => {
    const ids = await seedThree(page);
    // ALL THREE kinds of tracked NON-comment change that Copy all would normally carry, so a
    // regression in any one branch fails here rather than only the note one.
    await page.locator('[data-cmh-note="risk"] textarea, [data-cmh-note="risk"] input').first()
      .fill("Schedule risk is now amber.");
    await page.locator('[data-cmh-checklist="readiness"] [data-cmh-item="signoff"] .cmh-check').first().click();
    await moveBoardCard(page, "a", "later");
    await expect(page.locator(`${CARD}.cm-card-note`)).toHaveCount(1);
    await expect(page.locator(`${CARD}.cm-card-checklist`)).toHaveCount(1);
    await expect(page.locator(`${CARD}.cm-card-state`)).toHaveCount(1);

    await pick(page, ids[1]);
    await page.locator("#btnCopyAll").click();
    const bundle = await lastCopied(page);
    expect(bundle).toMatch(/^Scope: selected comments only \(1 of 3 open comment threads\)$/m);
    // The canonical empty {} in the trailer cannot say "withheld" apart from "nothing pending", so
    // the bundle names every tracked change kind it is holding back rather than letting the agent
    // guess - and the sections themselves stay out.
    expect(bundle).toMatch(/^Withheld: tracked widget-layout, checklist, note changes are still pending but are NOT in this partial hand-back/m);
    expect(bundle, "a selection is a COMMENT-only scope").not.toContain('## Note "risk"');
    expect(bundle).not.toContain('## Checklist "readiness"');
    expect(bundle).not.toContain("## Widget layout changes");
    const trailer = machineTrailerBody(bundle);
    expect(/NOTES_STATE_JSON: (.*)/.exec(trailer)[1].trim()).toBe("{}");
    expect(/CHECKLIST_STATE_JSON: (.*)/.exec(trailer)[1].trim()).toBe("{}");

    // ...and with no selection the same document still hands all three tracked changes back.
    await card(page, ids[1]).locator(PICK).uncheck();
    await expect(page.locator("#btnCopyAll")).toHaveText(/Copy all/);
    await page.locator("#btnCopyAll").click();
    const all = await lastCopied(page);
    expect(all).not.toMatch(/^Scope: selected comments only/m);
    expect(all).not.toMatch(/^Withheld:/m);
    expect(all).toContain('## Note "risk"');
    expect(all).toContain('## Checklist "readiness"');
    expect(all).toContain("## Widget layout changes");
    expect(all).toContain('"Card A" moved from Now to Later');
  });

  test("a partial hand-back with nothing withheld says so by staying silent (CMH-PICK-04)", async ({ page }) => {
    // The Withheld line must appear ONLY when tracked changes genuinely exist, or it becomes noise
    // the agent learns to ignore on every partial hand-back.
    const ids = await seedThree(page);
    await pick(page, ids[0]);
    await page.locator("#btnCopyAll").click();
    const bundle = await lastCopied(page);
    expect(bundle).toMatch(/^Scope: selected comments only \(1 of 3 open comment threads\)$/m);
    expect(bundle).not.toMatch(/^Withheld:/m);
  });

  test("Clear selection deselects everything and deletes nothing (CMH-PICK-05)", async ({ page }) => {
    const ids = await seedThree(page);
    await pick(page, ids[0]);
    await pick(page, ids[1]);
    await expect(page.locator("#cmSelectCount")).toHaveText(/2 comments selected/);

    await page.locator("#btnClearSelection").click();
    await expect(page.locator("#cmSelectBar")).toBeHidden();
    await expect(page.locator(`${CARD} ${PICK}:checked`)).toHaveCount(0);
    await expect(page.locator(`${CARD}.cm-card-picked`)).toHaveCount(0);
    await expect(page.locator("#btnCopyAll")).toHaveText(/Copy all/);
    // Nothing was deleted - clearing the SELECTION is not clearing the comments.
    await expect(page.locator(CARD)).toHaveCount(3);
    expect((await storedComments(page)).length).toBe(3);
  });

  test("Clear selection hands focus to a still-visible control (CMH-PICK-05)", async ({ page }) => {
    const ids = await seedThree(page);
    await pick(page, ids[0]);
    // Activating it hides the bar it lives in, and `.cm-skip [hidden]` removes that bar from the
    // layout - so without a hand-off the reviewer is left on `<body>`, having to Tab in from the
    // top of the document again (the CMH-THREAD-11 contract).
    await page.locator("#btnClearSelection").focus();
    await expect(page.locator("#btnClearSelection")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#cmSelectBar")).toBeHidden();
    await expect(page.locator("#btnCopyAll")).toBeFocused();
  });

  test("the collapsed toolbar can inspect and clear a selection too (CMH-PICK-05)", async ({ page }) => {
    const ids = await seedThree(page);
    await pick(page, ids[0]);
    await pick(page, ids[1]);
    // Hide the panel: the toolbar's overflow menu is the only chrome left, and it must not strand
    // the reviewer with a Copy selected button they can neither inspect nor undo.
    await page.click("#btnCloseSidebar");
    await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);

    await page.click("#btnToolbarMenu");
    await expect(page.locator("#toolbarMenu")).toBeVisible();
    const clear = page.locator("#btnClearSelectionTop");
    await expect(clear).toBeVisible();
    // It takes its place in the menu's tab order rather than being an orphan appended at the end:
    // between Save as PDF and the data-management pair, so Manage storage and Clear all stay
    // adjacent (CMH-UI-13).
    const around = await page.locator("#toolbarMenu").evaluate((el) => {
      const b = el.querySelector("#btnClearSelectionTop");
      return { prev: b.previousElementSibling.id, next: b.nextElementSibling.id };
    });
    expect(around).toEqual({ prev: "btnPrintTop", next: "btnStorageTop" });
    await clear.click();
    await expect(page.locator("#btnCopyAllTop")).toHaveText(/Copy all/);
    await expect(page.locator("#btnToolbarMenu")).toBeFocused();
    // Deselecting is not deleting.
    expect((await storedComments(page)).length).toBe(3);

    // With no selection the item is hidden again.
    await page.click("#btnToolbarMenu");
    await expect(page.locator("#toolbarMenu")).toBeVisible();
    await expect(clear).toBeHidden();
  });

  test("a pick the comment search hides is disclosed before it is deleted (CMH-PICK-09)", async ({ page }) => {
    const ids = await seedThree(page);
    await pick(page, ids[0]);   // "alpha note"
    await pick(page, ids[1]);   // "beta note"

    // Filter the list down to one of them. The other is still SELECTED and would still be deleted,
    // so the bar and the confirm have to say so - the filtered list otherwise implies the
    // selection was narrowed with it.
    await openSearch(page);
    await page.fill("#cmSearchInput", "beta");
    await expect(card(page, ids[0])).toHaveClass(/cm-hidden/);
    await expect(page.locator("#cmSelectCount")).toHaveText(/2 comments selected \(1 hidden by search\)/);

    await openSidebarMoreMenu(page);
    await page.locator("#btnClearSelected").click();
    const modal = page.locator(".cm-modal");
    await expect(modal).toBeVisible();
    await expect(modal).toContainText("1 of them is hidden by the current search.");
    await page.keyboard.press("Escape");

    // Clearing the filter drops the disclosure again.
    await page.locator("#cmSearchClear").click();
    await expect(page.locator(`${CARD}.cm-hidden`)).toHaveCount(0);
    await expect(page.locator("#cmSelectCount")).toHaveText(/^2 comments selected$/);
  });

  test("the selection bar and its menu item stay usable on a landscape phone (CMH-PICK-09)", async ({ page }) => {
    // 640x320 is the short landscape viewport CMH-RESP-16 bounds the header for. The selection bar
    // is a THIRD transient header row on top of the search and identity ones, so it must neither
    // take the comment list's usable window nor push its own menu item out of reach.
    await page.setViewportSize({ width: 640, height: 320 });
    const ids = await seedThree(page);
    await pick(page, ids[0]);
    await expect(page.locator("#cmSelectBar")).toBeVisible();

    const room = await page.evaluate(() => {
      const pane = document.querySelector(".cm-sidebar").getBoundingClientRect();
      const list = document.getElementById("commentList").getBoundingClientRect();
      return {
        visible: Math.min(list.bottom, pane.bottom, window.innerHeight) - Math.max(list.top, pane.top),
        clearH: document.getElementById("btnClearSelection").getBoundingClientRect().height,
        paneOverflow: document.querySelector(".cm-sidebar").scrollWidth - document.querySelector(".cm-sidebar").clientWidth,
      };
    });
    expect(room.visible, "the list keeps a usable scroll window while a selection is shown").toBeGreaterThanOrEqual(95);
    // The bar's control keeps at least the WCAG 2.5.8 AA floor here; the full 44px target is gated
    // on viewport HEIGHT, exactly like the search row's (CMH-RESP-16), so a transient row on a
    // short phone never costs the list its last usable height.
    expect(room.clearH, "Clear selection keeps the AA target floor").toBeGreaterThanOrEqual(24);
    expect(room.paneOverflow, "the bar does not scroll the pane sideways").toBeLessThanOrEqual(1);

    // ...and every More-menu item, including the selection-revealed one, is still reachable inside
    // the menu's short-viewport max-height.
    await openSidebarMoreMenu(page);
    const reach = await page.evaluate(() => {
      const el = document.getElementById("sidebarMoreMenu");
      const items = [...el.querySelectorAll("button:not([hidden])")];
      let worst = Infinity;
      for (const b of items) {
        b.scrollIntoView({ block: "nearest" });
        const box = el.getBoundingClientRect();
        const r = b.getBoundingClientRect();
        worst = Math.min(worst, Math.min(r.bottom, box.bottom) - Math.max(r.top, box.top) - r.height);
      }
      return { items: items.length, worst, ids: items.map((b) => b.id) };
    });
    expect(reach.ids, "the selection-revealed item is one of them").toContain("btnClearSelected");
    expect(reach.items, "every reachable item is measured").toBe(6);
    expect(reach.worst, "every item scrolls FULLY into the menu").toBeGreaterThanOrEqual(-0.5);
  });

  test("Clear selected comments shows only with a selection and deletes only those (CMH-PICK-06)", async ({ page }) => {
    const ids = await seedThree(page);
    // A REPLY under one of the selected roots, so the delete has a whole thread to take with it.
    await addReply(page, ids[0], "alpha refinement");
    const replyId = await page.locator(`${CARD} .cm-reply`).first().getAttribute("data-reply-cid");
    expect(replyId).toBeTruthy();

    await openSidebarMoreMenu(page);
    await expect(page.locator("#btnClearSelected")).toBeHidden();
    await page.keyboard.press("Escape");

    await pick(page, ids[0]);
    await pick(page, ids[2]);
    await openSidebarMoreMenu(page);
    await expect(page.locator("#btnClearSelected")).toBeVisible();
    await page.locator("#btnClearSelected").click();

    // It is destructive, so it confirms first, names the replies going with the roots - and
    // cancelling keeps every comment.
    const modal = page.locator(".cm-modal");
    await expect(modal).toBeVisible();
    await expect(modal).toContainText("Delete the 2 selected comments and 1 reply?");
    await page.keyboard.press("Escape");
    await expect(page.locator(CARD)).toHaveCount(3);
    expect((await storedComments(page)).length).toBe(4);

    await openSidebarMoreMenu(page);
    await page.locator("#btnClearSelected").click();
    await expect(page.locator(".cm-modal")).toBeVisible();
    await page.locator(".cm-modal button.danger, .cm-modal .cm-modal-ok").first().click();
    await expect(page.locator(".cm-modal")).toHaveCount(0);
    // The dialog's restoreFocus wiring hands focus back to the still-visible menu trigger rather
    // than stranding a keyboard reviewer on the removed modal.
    await expect(page.locator("#btnMoreMenu")).toBeFocused();

    await expect(page.locator(CARD)).toHaveCount(1);
    await expect(page.locator(`${CARD}[data-cid="${ids[1]}"]`)).toHaveCount(1);
    // The reply went with its root, not just the root.
    const left = await storedComments(page);
    expect(left.map((c) => c.id)).toEqual([ids[1]]);
    // ...and it stays gone across a reload (the whole thread was tombstoned, CMH-THREAD-02).
    await page.reload();
    await ready(page);
    expect((await storedComments(page)).map((c) => c.id)).toEqual([ids[1]]);
    // The selection went with the comments it named.
    await expect(page.locator("#cmSelectBar")).toBeHidden();
    await expect(page.locator("#btnCopyAll")).toHaveText(/Copy all/);
  });

  test("the selection is transient and prunes a deleted comment (CMH-PICK-07)", async ({ page }) => {
    const ids = await seedThree(page);
    // Snapshot the WHOLE store before picking: a selection must not change a single stored byte,
    // which is a far stronger claim than looking for one particular key name.
    const before = await page.evaluate(() => JSON.stringify(window.localStorage));
    await pick(page, ids[0]);
    await pick(page, ids[1]);
    const after = await page.evaluate(() => JSON.stringify(window.localStorage));
    expect(after, "picking writes nothing at all to storage").toBe(before);

    // Deleting a SELECTED comment through its own card drops it from the selection.
    page.once("dialog", (d) => d.accept());
    await card(page, ids[0]).locator('[data-act="del"]').click();
    await expect(page.locator(CARD)).toHaveCount(2);
    await expect(page.locator("#cmSelectCount")).toHaveText(/1 comment selected/);

    await page.reload();
    await ready(page);
    await expect(page.locator(CARD)).toHaveCount(2);
    await expect(page.locator("#cmSelectBar")).toBeHidden();
    await expect(page.locator(`${CARD} ${PICK}:checked`)).toHaveCount(0);
    await expect(page.locator("#btnCopyAll")).toHaveText(/Copy all/);

    // Clear all takes the rest of a selection with it rather than leaving stale ids behind.
    await pick(page, ids[1]);
    await clickClearAll(page);
    await expect(page.locator(".cm-modal")).toBeVisible();
    await page.locator(".cm-modal button.danger, .cm-modal .cm-modal-ok").first().click();
    await expect(page.locator(CARD)).toHaveCount(0);
    await expect(page.locator("#cmSelectBar")).toBeHidden();
    await expect(page.locator("#btnCopyAll")).toHaveText(/Copy all/);
  });

  test("a selection never travels inside an export (CMH-PICK-07)", async ({ page }) => {
    const ids = await seedThree(page);
    await pick(page, ids[0]);
    await pick(page, ids[1]);
    await expect(page.locator("#cmSelectCount")).toHaveText(/2 comments selected/);

    // Export WHILE a selection is live: the downloaded file must carry no trace of it, so a
    // recipient opens a document with nothing picked rather than inheriting the sender's view.
    const dl = page.waitForEvent("download");
    await clickSidebarExport(page, "#btnSaveHtml");
    const html = await readDownload(await dl);
    expect(html, "the selection chrome itself still ships").toContain('id="cmSelectBar"');
    expect(html, "...but hidden, with no card carrying the picked state").toMatch(/id="cmSelectBar"[^>]*\shidden/);
    // No ELEMENT carries the picked class (the class NAME is legitimately in the stylesheet).
    expect(html).not.toMatch(/class="[^"]*\bcm-card-picked\b/);
    // The embedded comments carry no per-comment selection flag either.
    const embedded = /<script type="application\/json" id="embeddedComments">\s*([\s\S]*?)\s*<\/script>/.exec(html);
    expect(embedded, "the export embedded its comments").toBeTruthy();
    const arr = JSON.parse(embedded[1]);
    expect(arr.length).toBe(3);
    arr.forEach((c) => {
      expect(Object.keys(c).join(","), "no selection flag rides along").not.toMatch(/pick|select/i);
    });
  });

  test("jump, edit and delete share the Reply row and its look and feel (CMH-PICK-08)", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "unified action row");
    const row = page.locator(`${CARD} .cm-card-actions`).first();
    await expect(row).toHaveCount(1);
    // All four actions live in that ONE row.
    for (const act of ["reply", "jump", "edit", "del"]) {
      await expect(row.locator(`[data-act="${act}"]`), `${act} is on the action row`).toHaveCount(1);
    }
    // ...and none of them is left behind on the meta line.
    for (const act of ["jump", "edit", "del"]) {
      await expect(page.locator(`${CARD} .cm-entry-root .meta [data-act="${act}"]`),
        `${act} is not duplicated on the meta line`).toHaveCount(0);
    }

    // Same look and feel as Reply: the shared button class, and the same border, radius and font.
    const look = await row.evaluate((el) => {
      const read = (sel) => {
        const b = el.querySelector(sel);
        const cs = getComputedStyle(b);
        return {
          klass: b.className,
          border: cs.borderTopWidth + " " + cs.borderTopStyle,
          radius: cs.borderTopLeftRadius,
          font: cs.fontSize,
          padding: cs.paddingTop + " " + cs.paddingLeft,
          top: Math.round(b.getBoundingClientRect().top),
        };
      };
      return {
        reply: read('[data-act="reply"]'),
        jump: read('[data-act="jump"]'),
        edit: read('[data-act="edit"]'),
        del: read('[data-act="del"]'),
      };
    });
    for (const act of ["jump", "edit", "del"]) {
      expect(look[act].klass, `${act} carries the shared card-button class`).toContain("cm-card-btn");
      expect(look[act].border, `${act} border matches Reply`).toBe(look.reply.border);
      expect(look[act].radius, `${act} radius matches Reply`).toBe(look.reply.radius);
      expect(look[act].font, `${act} font size matches Reply`).toBe(look.reply.font);
      expect(look[act].padding, `${act} padding matches Reply`).toBe(look.reply.padding);
      expect(look[act].top, `${act} sits on Reply's row`).toBe(look.reply.top);
    }

    // Opening the inline reply editor stands the WHOLE group down, so the composer owns the row -
    // hiding only the Reply button would leave jump/edit/delete sitting beside the textarea.
    const acts = page.locator(`${CARD} .cm-card-acts`).first();
    await page.locator(`${CARD} .cm-reply-btn`).first().click();
    await expect(page.locator(`${CARD} .cm-reply-compose`)).toHaveCount(1);
    await expect(acts).toBeHidden();
    for (const act of ["reply", "jump", "edit", "del"]) {
      await expect(page.locator(`${CARD} .cm-card-acts [data-act="${act}"]`),
        `${act} is not usable beside the composer`).toBeHidden();
    }
    // ...and cancelling gives the whole row back.
    await page.locator(`${CARD} .cm-reply-compose .cm-reply-cancel`).click();
    await expect(page.locator(`${CARD} .cm-reply-compose`)).toHaveCount(0);
    await expect(acts).toBeVisible();
    await expect(page.locator(`${CARD} .cm-card-acts [data-act="del"]`)).toBeVisible();
  });
});
