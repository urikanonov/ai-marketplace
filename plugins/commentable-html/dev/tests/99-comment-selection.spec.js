// Per-comment selection in the side pane: pick individual comment threads and hand back (or
// delete) only those, instead of the all-or-nothing Copy all / Clear all. Also covers the card's
// unified action row, where jump/edit/delete share the Reply button's row and look.
import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  openInline, addTextComment, installClipboardCapture, ready, fileUrl, stageContent,
  lastCopied, machineTrailerBody, storedComments, openSidebarMoreMenu,
} from "./helpers.js";

const CARD = "#commentList .cm-card";
const PICK = "input.cm-pick-box";

// A document whose prose can carry several distinct comments AND that owns an editable note, so
// the "a selection is a comment-only scope" rule has a tracked non-comment change to exclude.
const DOC = `
  <h1>Selection demo</h1>
  <p id="pa">Alpha paragraph for the first comment.</p>
  <p id="pb">Beta paragraph for the second comment.</p>
  <p id="pc">Gamma paragraph for the third comment.</p>
  <div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Reviewer risk summary">No blocking risks yet.</div>`;

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

test.describe("side-pane comment selection", () => {
  test("every comment card carries a Select control that picks that thread (CMH-PICK-01)", async ({ page }) => {
    const ids = await seedThree(page);
    // One obvious, keyboard-reachable, accessibly-named control per card.
    await expect(page.locator(`${CARD} ${PICK}`)).toHaveCount(3);
    const box = card(page, ids[1]).locator(PICK);
    await expect(box).not.toBeChecked();
    await expect(box).toHaveAttribute("aria-label", /select/i);

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

    await pick(page, ids[2]);
    await expect(page.locator("#cmSelectCount")).toHaveText(/2 comments selected/);

    // Dropping back to an empty selection restores the all-or-nothing default.
    await card(page, ids[0]).locator(PICK).uncheck();
    await card(page, ids[2]).locator(PICK).uncheck();
    await expect(copy).toHaveText(/Copy all/);
    await expect(page.locator("#btnCopyAllTop")).toHaveText(/Copy all/);
    await expect(page.locator("#cmSelectBar")).toBeHidden();
  });

  test("Copy selected emits only the selected threads, replies included (CMH-PICK-03)", async ({ page }) => {
    const ids = await seedThree(page);
    // Give the first comment a reply, so the thread-travels-together rule is exercised.
    await card(page, ids[0]).locator(".cm-reply-btn").click();
    const composer = page.locator(`${CARD} .cm-reply-compose`).last();
    await composer.locator("textarea").fill("alpha refinement");
    await composer.locator(".cm-reply-save").click();
    await expect(composer).toHaveCount(0);

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
    // A tracked NON-comment change that Copy all would normally carry.
    await page.locator('[data-cmh-note="risk"] textarea, [data-cmh-note="risk"] input').first()
      .fill("Schedule risk is now amber.");
    await expect(page.locator(`${CARD}.cm-card-note`)).toHaveCount(1);

    await pick(page, ids[1]);
    await page.locator("#btnCopyAll").click();
    const bundle = await lastCopied(page);
    expect(bundle).toMatch(/^Scope: selected comments only \(1 of 3 open comment threads\)$/m);
    expect(bundle, "a selection is a COMMENT-only scope").not.toContain('## Note "risk"');
    const trailer = machineTrailerBody(bundle);
    expect(/NOTES_STATE_JSON: (.*)/.exec(trailer)[1].trim()).toBe("{}");

    // ...and with no selection the same document still hands the note change back.
    await card(page, ids[1]).locator(PICK).uncheck();
    await expect(page.locator("#btnCopyAll")).toHaveText(/Copy all/);
    await page.locator("#btnCopyAll").click();
    const all = await lastCopied(page);
    expect(all).not.toMatch(/^Scope: selected comments only/m);
    expect(all).toContain('## Note "risk"');
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

  test("Clear selected comments shows only with a selection and deletes only those (CMH-PICK-06)", async ({ page }) => {
    const ids = await seedThree(page);
    await openSidebarMoreMenu(page);
    await expect(page.locator("#btnClearSelected")).toBeHidden();
    await page.keyboard.press("Escape");

    await pick(page, ids[0]);
    await pick(page, ids[2]);
    await openSidebarMoreMenu(page);
    await expect(page.locator("#btnClearSelected")).toBeVisible();
    await page.locator("#btnClearSelected").click();

    // It is destructive, so it confirms first - and cancelling keeps every comment.
    await expect(page.locator(".cm-modal")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(CARD)).toHaveCount(3);

    await openSidebarMoreMenu(page);
    await page.locator("#btnClearSelected").click();
    await expect(page.locator(".cm-modal")).toBeVisible();
    await page.locator(".cm-modal button.danger, .cm-modal .cm-modal-ok").first().click();
    await expect(page.locator(".cm-modal")).toHaveCount(0);

    await expect(page.locator(CARD)).toHaveCount(1);
    await expect(page.locator(`${CARD}[data-cid="${ids[1]}"]`)).toHaveCount(1);
    const left = await storedComments(page);
    expect(left.map((c) => c.id)).toEqual([ids[1]]);
    // The selection went with the comments it named.
    await expect(page.locator("#cmSelectBar")).toBeHidden();
    await expect(page.locator("#btnCopyAll")).toHaveText(/Copy all/);
  });

  test("the selection is transient and prunes a deleted comment (CMH-PICK-07)", async ({ page }) => {
    const ids = await seedThree(page);
    await pick(page, ids[0]);
    await pick(page, ids[1]);

    // Deleting a SELECTED comment through its own card drops it from the selection.
    page.once("dialog", (d) => d.accept());
    await card(page, ids[0]).locator('[data-act="del"]').click();
    await expect(page.locator(CARD)).toHaveCount(2);
    await expect(page.locator("#cmSelectCount")).toHaveText(/1 comment selected/);

    // The selection is a view of THIS session: it is never written to the store, so a reload
    // starts from the all-or-nothing default.
    const raw = await page.evaluate(() => JSON.stringify(window.localStorage));
    expect(raw).not.toContain("cmSelect");
    expect(raw).not.toContain("picked");
    await page.reload();
    await ready(page);
    await expect(page.locator(CARD)).toHaveCount(2);
    await expect(page.locator("#cmSelectBar")).toBeHidden();
    await expect(page.locator(`${CARD} ${PICK}:checked`)).toHaveCount(0);
    await expect(page.locator("#btnCopyAll")).toHaveText(/Copy all/);
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
    await expect(page.locator(`${CARD} .cm-entry-root .meta [data-act="jump"]`)).toHaveCount(0);

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
  });
});
