// Editable notes fields: a data-cmh-note element becomes an editable <textarea> whose baseline is
// its authored text; edits persist as a minimal delta, surface as a per-note change card, flip the
// badge, travel through Copy all as NOTES_STATE_JSON, bake into the source on export, and round-trip
// back to the source via tools/notes/notes_apply.py.
import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import path from "path";
import {
  fileUrl, ready, installClipboardCapture, stageContent, copiedBundle, readDownload,
  addTextComment, SKILL, PYTHON,
  clickSidebarExport,
} from "./helpers.js";

const NOTES_APPLY = path.join(SKILL, "tools", "notes", "notes_apply.py");

const DOC = `
  <h1>Notes demo</h1>
  <p id="before">Leading prose before the note.</p>
  <div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Reviewer risk summary">No blocking risks yet.</div>
  <p id="after">Trailing prose after the note.</p>`;

// A normalization-hostile value: leading/trailing spaces, an internal double space, and an entity
// char, so a test cannot pass by accident. normalizeNote trims the outer whitespace only.
const HOSTILE = "  One blocker: not  reversible < &  ";
const HOSTILE_NORM = "One blocker: not  reversible < &";

async function open(page, content, key) {
  await installClipboardCapture(page);
  const { html, dir } = stageContent(content, { key });
  await page.goto(fileUrl(html));
  await ready(page);
  return { html, dir };
}

const field = (page) => page.locator('[data-cmh-note="risk"] .cmh-note-input');
const storedNotes = (page) => page.evaluate(() => {
  const k = document.getElementById("commentRoot").dataset.commentKey + "::note";
  const raw = localStorage.getItem(k);
  return raw ? JSON.parse(raw) : null;
});

test("CMH-NOTE-01: authored note upgrades to an editable textarea (cm-skip, ready, toggle)", async ({ page }) => {
  await open(page, DOC, "cmh-note-01");
  await expect(page.locator(".cmh-note.cmh-note-ready")).toHaveCount(1);
  await expect(page.locator('[data-cmh-note="risk"]')).toHaveClass(/cm-skip/);
  await expect(field(page)).toBeVisible();
  await expect(field(page)).toHaveJSProperty("tagName", "TEXTAREA");
  await expect(field(page)).toHaveValue("No blocking risks yet.");
  await expect(page.locator('[data-cmh-note="risk"] .cmh-note-toggle')).toBeVisible();
});

test("CMH-NOTE-02: an edit persists a minimal delta, restores on reload, and prunes at baseline", async ({ page }) => {
  const { html } = await open(page, DOC, "cmh-note-02");
  await field(page).fill(HOSTILE);
  expect(await storedNotes(page)).toEqual({ risk: HOSTILE_NORM });
  await page.goto(fileUrl(html));
  await ready(page);
  await expect(field(page)).toHaveValue(HOSTILE_NORM);
  // Editing back to the exact baseline prunes the entry entirely.
  await field(page).fill("No blocking risks yet.");
  expect(await storedNotes(page)).toBeNull();
});

test("CMH-NOTE-03: the single/multi-line toggle switches the field height", async ({ page }) => {
  await open(page, DOC, "cmh-note-03");
  const note = page.locator('[data-cmh-note="risk"]');
  await expect(note).toHaveClass(/cmh-note-single/);
  await expect(field(page)).toHaveJSProperty("rows", 1);
  await note.locator(".cmh-note-toggle").click();
  await expect(note).toHaveClass(/cmh-note-multiline/);
  expect(await field(page).evaluate((el) => el.rows)).toBeGreaterThan(1);
});

test("CMH-NOTE-04: a changed note renders one non-comment card by document order; count stays 0", async ({ page }) => {
  await open(page, DOC, "cmh-note-04");
  await expect(page.locator(".cm-card-note")).toHaveCount(0);
  await addTextComment(page, "#before", "before note");
  await field(page).fill(HOSTILE);
  const card = page.locator(".cm-card-note");
  await expect(card).toHaveCount(1);
  await expect(card).toContainText("Reviewer risk summary");
  await expect(card.locator('[data-act="note-jump"]')).toHaveText("jump");
  await expect(card.locator('[data-act="note-reset"]')).toHaveText("reset");
  await expect(page.locator("#sidebarCount")).toHaveText("1");  // only the real comment counts
  // The note (after #before) sorts after that comment's card.
  const order = await page.$$eval("#commentList > article", (els) =>
    els.map((e) => e.classList.contains("cm-card-note") ? "NOTE" : (e.querySelector(".note") || {}).textContent));
  expect(order.indexOf("NOTE")).toBeGreaterThan(order.indexOf("before note"));
});

test("CMH-NOTE-05: reset reverts the note to its authored baseline", async ({ page }) => {
  await open(page, DOC, "cmh-note-05");
  await field(page).fill(HOSTILE);
  await page.locator('.cm-card-note [data-act="note-reset"]').click();
  await expect(page.locator(".cm-card-note")).toHaveCount(0);
  await expect(field(page)).toHaveValue("No blocking risks yet.");
  expect(await storedNotes(page)).toBeNull();
});

test("CMH-NOTE-06: Clear all comments also reverts note edits to baseline", async ({ page }) => {
  await open(page, DOC, "cmh-note-06");
  await addTextComment(page, "#before", "a comment");
  await field(page).fill(HOSTILE);
  await expect(page.locator(".cm-card-note")).toHaveCount(1);
  await page.click("#btnClearAll");
  await expect(page.locator(".cm-modal")).toBeVisible();
  await page.locator(".cm-modal").getByRole("button", { name: "OK" }).click();
  await expect(page.locator(".cm-card-note")).toHaveCount(0);
  await expect(field(page)).toHaveValue("No blocking risks yet.");
  expect(await storedNotes(page)).toBeNull();
});

test("CMH-NOTE-07: an unsaved note edit flips the badge to Not portable, naming the note", async ({ page }) => {
  await open(page, DOC, "cmh-note-07");
  await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
  await field(page).fill(HOSTILE);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");
  const reason = await page.getAttribute("#cmTypeBadge", "title");
  expect(reason).toContain("note");
});

test("CMH-NOTE-08: Copy all includes a Note section and NOTES_STATE_JSON", async ({ page }) => {
  await open(page, DOC, "cmh-note-08");
  await field(page).fill(HOSTILE);
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toContain('## Note "risk"');
  expect(bundle).toContain("Reviewer risk summary");
  expect(bundle).toContain(HOSTILE_NORM);
  expect(bundle).toContain('NOTES_STATE_JSON: {"risk":"' + HOSTILE_NORM + '"}');
});

test("CMH-NOTE-09: export bakes note text into the source element with no editing attributes", async ({ page }) => {
  await open(page, DOC, "cmh-note-09");
  await field(page).fill(HOSTILE);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnSaveHtml"),
  ]);
  const html = await readDownload(download);
  expect(html).toContain("One blocker: not  reversible &lt; &amp;");
  // The baked note element carries the text but none of the runtime editing attributes, so a
  // reopened export opens clean (the reopen-zero-pending round-trip is proven in CMH-NOTE-E2E).
  const noteTag = html.match(/<div[^>]*data-cmh-note="risk"[^>]*>/);
  expect(noteTag).not.toBeNull();
  expect(noteTag[0]).not.toContain("contenteditable");
  expect(noteTag[0]).not.toContain("cmh-note-ready");
});

test("CMH-NOTE-10: a changed note is searchable in the sidebar", async ({ page }) => {
  await open(page, DOC, "cmh-note-10");
  await field(page).fill(HOSTILE);
  const search = page.locator("#cmSearchInput");
  await search.fill("blocker");   // matches the note text
  await expect(page.locator(".cm-card-note")).toBeVisible();
  await search.fill("nonexistent-term-xyz");
  await expect(page.locator(".cm-card-note")).toBeHidden();
});

test("CMH-NOTE-11: a note that loads with a persisted edit opens the sidebar", async ({ page }) => {
  const { html } = await open(page, DOC, "cmh-note-11");
  await field(page).fill(HOSTILE);
  await page.goto(fileUrl(html));
  await ready(page);
  await expect(page.locator("body")).toHaveClass(/sidebar-open/);
  await expect(page.locator(".cm-card-note")).toHaveCount(1);
});

test("CMH-NOTE-12: the note field is cm-skip; editing it never creates a highlight", async ({ page }) => {
  await open(page, DOC, "cmh-note-12");
  await field(page).click();
  await field(page).fill(HOSTILE);
  await expect(page.locator("mark.cm-hl")).toHaveCount(0);
  await expect(page.locator("#sidebarCount")).toHaveText("0");
});

test("CMH-NOTE-E2E: reviewer edit -> Copy all -> notes_apply.py -> reopen shows the cemented source", async ({ page }) => {
  const { html, dir } = await open(page, DOC, "cmh-note-e2e");
  // 1. Edit the note and capture the real Copy-all bundle.
  await field(page).fill(HOSTILE);
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toContain("NOTES_STATE_JSON:");
  const bundlePath = path.join(dir, "bundle.txt");
  fs.writeFileSync(bundlePath, bundle);

  // 2. Cement the edit into the SOURCE file with the real tool.
  const res = spawnSync(PYTHON, [NOTES_APPLY, html, "--from-bundle", bundlePath], { encoding: "utf8" });
  expect(res.status, res.stderr).toBe(0);
  const rawSource = fs.readFileSync(html, "utf8");
  expect(rawSource).toContain("One blocker: not  reversible &lt; &amp;");

  // 3. Reopen the SAME file in the SAME context (the stale localStorage override is deliberately
  // kept): a green here can only mean the SOURCE was cemented, because the override now equals the
  // new baseline and is pruned, leaving no pending change.
  await page.goto(fileUrl(html));
  await ready(page);
  await expect(field(page)).toHaveValue(HOSTILE_NORM);
  await expect(page.locator(".cm-card-note")).toHaveCount(0);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
  expect(await storedNotes(page)).toBeNull();
});

// Foldable notes: a +/- disclosure that reveals the field on the line below.
const FOLD_DOC = `
  <h1>Foldable notes demo</h1>
  <p id="before">Leading prose before the notes.</p>
  <div class="cmh-note" data-cmh-note="empty-fold" data-cmh-note-label="Add a note" data-cmh-note-foldable="true"></div>
  <div class="cmh-note" data-cmh-note="content-fold" data-cmh-note-label="Sign-off" data-cmh-note-foldable="true">Looks good.</div>
  <div class="cmh-note" data-cmh-note="plain" data-cmh-note-label="Plain">Plain note.</div>`;
const foldBtn = (page, id) => page.locator(`[data-cmh-note="${id}"] .cmh-note-fold`);
const noteInput = (page, id) => page.locator(`[data-cmh-note="${id}"] .cmh-note-input`);

test("CMH-NOTE-16: a foldable note starts collapsed only when empty and toggles with the +/- control", async ({ page }) => {
  await open(page, FOLD_DOC, "cmh-note-16a");
  // Empty foldable note starts collapsed (field hidden, aria-expanded false).
  await expect(noteInput(page, "empty-fold")).toBeHidden();
  await expect(foldBtn(page, "empty-fold")).toHaveAttribute("aria-expanded", "false");
  // A foldable note WITH content starts expanded (your rule: content is not hidden).
  await expect(noteInput(page, "content-fold")).toBeVisible();
  await expect(foldBtn(page, "content-fold")).toHaveAttribute("aria-expanded", "true");
  // A non-foldable note has no fold control and stays visible.
  await expect(foldBtn(page, "plain")).toHaveCount(0);
  await expect(noteInput(page, "plain")).toBeVisible();
  // Clicking + expands the empty note, clicking - collapses it again.
  await foldBtn(page, "empty-fold").click();
  await expect(noteInput(page, "empty-fold")).toBeVisible();
  await expect(foldBtn(page, "empty-fold")).toHaveAttribute("aria-expanded", "true");
  await foldBtn(page, "empty-fold").click();
  await expect(noteInput(page, "empty-fold")).toBeHidden();
});

test("CMH-NOTE-16: keyboard toggles the fold, and a collapsed note with content shows a badge", async ({ page }) => {
  await open(page, FOLD_DOC, "cmh-note-16b");
  await foldBtn(page, "content-fold").focus();
  await page.keyboard.press("Enter");
  await expect(noteInput(page, "content-fold")).toBeHidden();
  // A collapsed note that still holds content is badged; an empty collapsed note is not.
  await expect(page.locator('[data-cmh-note="content-fold"]')).toHaveClass(/cmh-note-has-content/);
  await expect(page.locator('[data-cmh-note="empty-fold"]')).not.toHaveClass(/cmh-note-has-content/);
});

test("CMH-NOTE-16: a foldable note with a persisted edit auto-expands on reload; jump expands a collapsed note", async ({ page }) => {
  const { html } = await open(page, FOLD_DOC, "cmh-note-16c");
  await foldBtn(page, "empty-fold").click();          // expand before editing
  await noteInput(page, "empty-fold").fill("a real note");
  await page.goto(fileUrl(html));                      // reload: it now has content, so it opens expanded
  await ready(page);
  await expect(noteInput(page, "empty-fold")).toBeVisible();
  await expect(foldBtn(page, "empty-fold")).toHaveAttribute("aria-expanded", "true");
  // Manually collapse it, then jump from its change card: the note expands.
  await foldBtn(page, "empty-fold").click();
  await expect(noteInput(page, "empty-fold")).toBeHidden();
  await page.locator('.cm-card-note[data-cmh-note-name="empty-fold"] [data-act="note-jump"]').click();
  await expect(noteInput(page, "empty-fold")).toBeVisible();
});

test("CMH-NOTE-16: fold state is presentation only - the export keeps data-cmh-note-foldable but no runtime collapse", async ({ page }) => {
  await open(page, FOLD_DOC, "cmh-note-16d");
  // An edit on one note enables Save (and triggers the note export bake).
  await foldBtn(page, "empty-fold").click();
  await noteInput(page, "empty-fold").fill("edited");
  // Collapse a DIFFERENT foldable note (a pure view change, no edit).
  await foldBtn(page, "content-fold").click();
  await expect(noteInput(page, "content-fold")).toBeHidden();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnSaveHtml"),
  ]);
  const html = await readDownload(download);
  // Scope to the collapsed note's own tag (the inlined runtime legitimately mentions the class).
  const tag = html.match(/<div[^>]*data-cmh-note="content-fold"[^>]*>/);
  expect(tag).not.toBeNull();
  expect(tag[0]).toContain('data-cmh-note-foldable="true"');
  expect(tag[0]).not.toContain("cmh-note-collapsed");
});
