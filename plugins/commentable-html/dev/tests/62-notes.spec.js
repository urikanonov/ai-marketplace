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
  clickClearAll, openSearch,
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

test("CMH-NOTE-04: a changed note renders one non-comment card by document order and is counted", async ({ page }) => {
  await open(page, DOC, "cmh-note-04");
  await expect(page.locator(".cm-card-note")).toHaveCount(0);
  await field(page).fill(HOSTILE);
  const card = page.locator(".cm-card-note");
  await expect(card).toHaveCount(1);
  await expect(card).toContainText("Reviewer risk summary");
  await expect(card.locator('[data-act="note-jump"]')).toHaveText("jump");
  await expect(card.locator('[data-act="note-reset"]')).toHaveText("reset");
  // A changed note alone is reflected in BOTH counters, so it is not mistaken for no change (issue #643).
  await expect(page.locator("#sidebarCount")).toHaveText("1");
  await expect(page.locator("#toolbarCount")).toHaveText("1");
  // Adding a real comment brings the count to 2 (the comment plus the changed note).
  await addTextComment(page, "#before", "before note");
  await expect(page.locator("#sidebarCount")).toHaveText("2");
  await expect(page.locator("#toolbarCount")).toHaveText("2");
  // The note (after #before) sorts after that comment's card.
  const order = await page.$$eval("#commentList > article", (els) =>
    els.map((e) => e.classList.contains("cm-card-note") ? "NOTE" : (e.querySelector(".note") || {}).textContent));
  expect(order.indexOf("NOTE")).toBeGreaterThan(order.indexOf("before note"));
});

test("CMH-NOTE-05: reset reverts the note to its authored baseline", async ({ page }) => {
  await open(page, DOC, "cmh-note-05");
  await field(page).fill(HOSTILE);
  await expect(page.locator("#sidebarCount")).toHaveText("1");  // the changed note is counted
  await page.locator('.cm-card-note [data-act="note-reset"]').click();
  await expect(page.locator(".cm-card-note")).toHaveCount(0);
  await expect(field(page)).toHaveValue("No blocking risks yet.");
  expect(await storedNotes(page)).toBeNull();
  // Reverting the only change returns BOTH counters to 0 (issue #643).
  await expect(page.locator("#sidebarCount")).toHaveText("0");
  await expect(page.locator("#toolbarCount")).toHaveText("0");
});

test("CMH-NOTE-06: Delete all comments also reverts note edits to baseline", async ({ page }) => {
  await open(page, DOC, "cmh-note-06");
  await addTextComment(page, "#before", "a comment");
  await field(page).fill(HOSTILE);
  await expect(page.locator(".cm-card-note")).toHaveCount(1);
  await clickClearAll(page);
  await expect(page.locator(".cm-modal")).toBeVisible();
  // The confirm names the note reset alongside the comment deletion (a comment is present here).
  await expect(page.locator(".cm-modal")).toContainText(
    "Delete all 1 comment(s) and reset any tracked widget, checklist, and note changes");
  await page.locator(".cm-modal").getByRole("button", { name: "OK" }).click();
  await expect(page.locator(".cm-card-note")).toHaveCount(0);
  await expect(field(page)).toHaveValue("No blocking risks yet.");
  expect(await storedNotes(page)).toBeNull();
});

test("CMH-NOTE-06: Delete all reverts a note-only change even with no comment present", async ({ page }) => {
  await open(page, DOC, "cmh-note-06b");
  // A note edit is the ONLY pending change (no comments, no checklist/widget changes). Clear all
  // used to treat this as "nothing to clear" and no-op; it must now open the confirm and reset it.
  await field(page).fill(HOSTILE);
  await expect(page.locator(".cm-card-note")).toHaveCount(1);
  await clickClearAll(page);
  await expect(page.locator(".cm-modal")).toBeVisible();
  // With no comment present, the confirm names only the resets - no "Delete all 0 comment(s)" clause.
  await expect(page.locator(".cm-modal")).toContainText(
    "Reset any tracked widget, checklist, and note changes");
  await expect(page.locator(".cm-modal")).not.toContainText("comment(s)");
  await page.locator(".cm-modal").getByRole("button", { name: "OK" }).click();
  await expect(page.locator(".cm-card-note")).toHaveCount(0);
  await expect(field(page)).toHaveValue("No blocking risks yet.");
  expect(await storedNotes(page)).toBeNull();
});

test("CMH-NOTE-07: an unsaved note edit flips the badge to Not shareable, naming the note", async ({ page }) => {
  await open(page, DOC, "cmh-note-07");
  await expect(page.locator("#cmTypeBadge")).toHaveText("Shareable");
  await field(page).fill(HOSTILE);
  await expect(page.locator("#cmTypeBadge")).toHaveText("Not shareable");
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
  await openSearch(page);
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
  // Editing the note creates no comment highlight, but the changed note is reflected in the count.
  await expect(page.locator("#sidebarCount")).toHaveText("1");
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
  await expect(page.locator("#cmTypeBadge")).toHaveText("Shareable");
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

// The runtime STATE classes must be self-sufficient: `class="cmh-note"` is author card chrome, so a
// hand-written / retrofitted / class-rewritten note that carries only `data-cmh-note` still folds
// (issue #1242 - the collapse rules were qualified with the author class the glyph rule omitted, so
// the button reacted while the field stayed open).
const FOLD_DOC_NO_CLASS = `
  <h1>Foldable note without the author class</h1>
  <p id="before">Leading prose before the note.</p>
  <div data-cmh-note="bare-fold" data-cmh-note-label="Sign-off" data-cmh-note-foldable="true">Looks good.</div>`;

test("CMH-NOTE-16: hide collapses a foldable note carrying no author cmh-note class", async ({ page }) => {
  await open(page, FOLD_DOC_NO_CLASS, "cmh-note-16e");
  const note = page.locator('[data-cmh-note="bare-fold"]');
  await expect(note).not.toHaveClass(/(^|\s)cmh-note(\s|$)/);
  await expect(noteInput(page, "bare-fold")).toBeVisible();
  // The single-line state rule is runtime-owned too: it must shape the field without the card class.
  await expect(note).toHaveClass(/cmh-note-single/);
  await expect(noteInput(page, "bare-fold")).toHaveCSS("white-space", "nowrap");
  await foldBtn(page, "bare-fold").click();
  await expect(noteInput(page, "bare-fold")).toBeHidden();
  await expect(page.locator('[data-cmh-note="bare-fold"] .cmh-note-toggle')).toBeHidden();
  await expect(foldBtn(page, "bare-fold")).toHaveAttribute("aria-expanded", "false");
  // ...and the has-content badge, the third runtime-owned state rule, still renders.
  await expect(note).toHaveClass(/cmh-note-has-content/);
  const badge = await page.locator('[data-cmh-note="bare-fold"] .cmh-note-label')
    .evaluate((el) => getComputedStyle(el, "::after").display);
  expect(badge).toBe("inline");
  await foldBtn(page, "bare-fold").click();
  await expect(noteInput(page, "bare-fold")).toBeVisible();
});

// A runtime STATE class in the AUTHORED markup is not an instruction: the runtime owns those names
// and clears them at load, so a note cannot be authored into a state its controls cannot undo (a
// non-foldable note wearing cmh-note-collapsed would otherwise hide its own field for good).
const STALE_STATE_DOC = `
  <h1>Note carrying a stale runtime state class</h1>
  <div class="cmh-note-collapsed cmh-note-has-content" data-cmh-note="stale" data-cmh-note-label="Stale">Authored text.</div>`;

test("CMH-NOTE-16: an authored runtime state class is cleared, so the field is never stuck hidden", async ({ page }) => {
  await open(page, STALE_STATE_DOC, "cmh-note-16g");
  const note = page.locator('[data-cmh-note="stale"]');
  await expect(note).not.toHaveClass(/cmh-note-collapsed/);
  await expect(note).not.toHaveClass(/cmh-note-has-content/);
  await expect(noteInput(page, "stale")).toBeVisible();
  // It is not foldable, so there is no control that could have revealed it had it stayed collapsed.
  await expect(foldBtn(page, "stale")).toHaveCount(0);
});

// Relative luminance / contrast ratio per WCAG 2.x, so the assertion is about LEGIBILITY rather
// than mere string inequality (an almost-invisible glyph would pass a !== check).
function _contrastRatio(fg, bg) {
  const parse = (s) => {
    const m = String(s).match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(",").map((v) => parseFloat(v.trim()));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = (c) => {
    const ch = [c.r, c.g, c.b].map((v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };
  const f = parse(fg), b = parse(bg);
  if (!f || !b) return null;
  const [hi, lo] = [lum(f), lum(b)].sort((x, y) => y - x);
  return { ratio: (hi + 0.05) / (lo + 0.05), bgAlpha: b.a };
}

test("CMH-NOTE-16: the fold button keeps its +/- glyph legible on hover", async ({ page }) => {
  await open(page, FOLD_DOC, "cmh-note-16f");
  const btn = foldBtn(page, "content-fold");
  // The glyph is a ::before, so read ITS color, not the button's own computed color.
  const paint = () => btn.evaluate((el) => ({
    glyph: getComputedStyle(el, "::before").color,
    background: getComputedStyle(el).backgroundColor,
  }));
  const rest = await paint();
  await btn.hover();
  // Poll rather than read once: the :hover repaint is not guaranteed to have landed the instant
  // hover() resolves, and a fixed sleep would be either flaky or wasteful.
  await expect.poll(async () => (await paint()).background).not.toBe(rest.background);
  const hovered = await paint();
  // 1. Hover is a REAL cue: the fill actually changes (the pre-fix rule and a hover rule deleted
  //    outright would both leave the fill untouched here).
  expect(hovered.background).not.toBe(rest.background);
  // 2. The glyph stays legible ON that fill. Painting the fill in the glyph's own token erased the
  //    +/- entirely (issue #1242); a merely low-contrast fill fails this too.
  const hoverContrast = _contrastRatio(hovered.glyph, hovered.background);
  expect(hoverContrast, `unparsed colors: ${JSON.stringify(hovered)}`).not.toBeNull();
  expect(hoverContrast.bgAlpha).toBe(1);
  expect(hoverContrast.ratio).toBeGreaterThanOrEqual(4.5);
  // 3. Both halves hold in the DARK theme too, which swaps BOTH tokens the rule pairs
  //    (--cp-accent and --cp-accent-fg), so a dark-only break cannot slip through. The pointer has
  //    not moved, so the button is still hovered; only the tokens change.
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
  await expect.poll(async () => (await paint()).background).not.toBe(hovered.background);
  const dark = await paint();
  const darkContrast = _contrastRatio(dark.glyph, dark.background);
  expect(darkContrast, `unparsed dark colors: ${JSON.stringify(dark)}`).not.toBeNull();
  expect(darkContrast.bgAlpha).toBe(1);
  expect(darkContrast.ratio).toBeGreaterThanOrEqual(4.5);
});

test("CMH-NOTE-16: print reveals a collapsed class-less note", async ({ page }) => {
  await open(page, FOLD_DOC_NO_CLASS, "cmh-note-16h");
  await foldBtn(page, "bare-fold").click();
  await expect(noteInput(page, "bare-fold")).toBeHidden();
  // The print override must reach the same de-qualified note the screen rules do, so a reviewer
  // never prints a document with a collapsed note's text silently missing.
  await page.emulateMedia({ media: "print" });
  await expect(noteInput(page, "bare-fold")).toBeVisible();
  await page.emulateMedia({ media: "screen" });
  await expect(noteInput(page, "bare-fold")).toBeHidden();
});

test("CMH-NOTE-17: typing coalesces the sidebar re-render (one debounced render per burst, not one per keystroke)", async ({ page }) => {
  await open(page, DOC, "cmh-note-17");
  // Fire a burst of input events SYNCHRONOUSLY in one JS turn. renderComments() runs two
  // full-document tree walks; the typing path must coalesce the burst into a single deferred
  // render, so no render can run while the stack is still unwound (issue #505). On the pre-fix
  // code each event re-rendered synchronously, so the render counter would be 30 here. docScans
  // counts widgetStateChanges() (the document-wide widget scan the badge / Copy-all helpers run):
  // the sync UI is gated on the dirty transition, so the whole burst triggers it only once (on the
  // first, dirtying keystroke, via updateDocTypeUi + updateCopyAllState = 2), not per keystroke - a
  // regression that dropped the transition gate would run ~60 scans here even though renders stays 1.
  const burst = await page.evaluate(() => {
    const ta = document.querySelector('[data-cmh-note="risk"] .cmh-note-input');
    window.__cmhPerf = { renders: 0, docScans: 0 };
    for (let i = 0; i < 30; i++) {
      ta.value += "x";
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    return { renders: window.__cmhPerf.renders, docScans: window.__cmhPerf.docScans };
  });
  expect(burst.renders).toBe(0);
  // The document-scan helpers ran only on the single dirty-state transition, not per keystroke.
  expect(burst.docScans).toBeLessThanOrEqual(2);
  // The edit is not lost: after the reviewer pauses, exactly the final text renders as one card,
  // and the whole burst cost a single coalesced render (not two - the flush renders exactly once).
  await expect(page.locator(".cm-card-note")).toHaveCount(1);
  await expect(field(page)).toHaveValue("No blocking risks yet." + "x".repeat(30));
  const total = await page.evaluate(() => window.__cmhPerf.renders);
  expect(total).toBe(1);
  // The delta is persisted synchronously per keystroke, so no edit is lost mid-burst.
  expect(await storedNotes(page)).toEqual({ risk: "No blocking risks yet." + "x".repeat(30) });
});

test("CMH-NOTE-17: a Copy all during the debounce window reflects the latest text and the badge updates synchronously", async ({ page }) => {
  await open(page, DOC, "cmh-note-17b");
  // Dispatch the input, read the badge, AND trigger Copy all - all in ONE synchronous browser turn,
  // so the 150ms debounce provably cannot have fired. copyAll() builds its bundle from live note
  // state and calls the (synchronously-capturing) clipboard shim before its first await, so this
  // pins both the synchronous badge update and that a mid-debounce Copy all carries the latest text.
  const { badge, bundle } = await page.evaluate(() => {
    const ta = document.querySelector('[data-cmh-note="risk"] .cmh-note-input');
    ta.value = "typed but not yet rendered";
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    const badge = document.getElementById("cmTypeBadge").textContent;
    document.getElementById("btnCopyAll").click();
    return { badge, bundle: (window.__copied && window.__copied[window.__copied.length - 1]) || null };
  });
  expect(badge).toBe("Not shareable");
  expect(bundle).toContain('NOTES_STATE_JSON: {"risk":"typed but not yet rendered"}');
});
