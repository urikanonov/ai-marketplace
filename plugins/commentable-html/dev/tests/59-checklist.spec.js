// Layered checklist: four-state item checkboxes (blank/check/cross/question) with pretty
// icons, parent aggregation over direct children, top-down propagation, minimal delta
// persistence, one per-list state card (jump + reset) placed by document order, a Copy-all
// section with CHECKLIST_STATE_JSON, and an export bake into data-cmh-state.
import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";
import os from "os";
import {
  fileUrl, ready, installClipboardCapture, stageContent, copiedBundle, readDownload,
  addTextComment, SKILL,
  clickSidebarExport,
  clickClearAll,
  routeExampleLibsLocal,
} from "./helpers.js";

const CHECKLIST_DEMO = path.join(SKILL, "..", "..", "examples", "report-checklist.html");

for (const [layout, width] of [["desktop", 1280], ["mobile", 390]]) {
  test(`combined dynamic controls round-trip on ${layout} (CMH-DEMO-04)`, async ({ page }) => {
    test.slow();
    await page.setViewportSize({ width, height: 900 });
    await installClipboardCapture(page);
    await routeExampleLibsLocal(page);
    await page.goto(fileUrl(CHECKLIST_DEMO));
    await ready(page);
    const table = page.locator('[data-cmh-table="followups"]');
    const note = page.locator('[data-cmh-note="verdict"] textarea');
    for (const tool of ["checklist_apply.py", "notes_apply.py", "tables_apply.py"]) {
      await expect(page.locator("#about-example").locator("..")).toContainText(tool);
    }
    await expect(table).toHaveCount(1);
    if (layout === "mobile") {
      const title = table.locator('[data-cmh-column="action"] .cmh-table-title');
      expect((await title.boundingBox()).width).toBeGreaterThanOrEqual(90);
    }
    await expect(page.locator(".cmh-checklist.cmh-checklist-ready")).toHaveCount(2);
    await note.fill("Hold until follow-ups are resolved.");
    if (layout === "mobile") await page.locator("#btnCloseSidebar").click();
    await ctrl(page, "rollback").click();
    if (layout === "mobile") await page.locator("#btnCloseSidebar").click();
    await table.locator('[data-cmh-row="loadtest"] [data-cmh-edit-column="owner"]').fill("Taylor");
    if (layout === "mobile") await page.locator("#btnCloseSidebar").click();
    await page.locator(".cmh-editable-table").getByRole("button", { name: "Add row", exact: true }).click();
    await expect(table.locator("tbody tr")).toHaveCount(4);
    await expect(page.locator(".cm-card-table")).toHaveCount(1);
    await expect(page.locator(".cm-card-note")).toHaveCount(1);
    await expect(page.locator(".cm-card-checklist")).toHaveCount(1);
    if (layout === "mobile") await page.locator("#btnToggleSidebar").click();
    await expect(page.locator("#btnCopyAll")).toBeInViewport();
    await page.locator("#btnCopyAll").click();
    const bundle = await copiedBundle(page);
    for (const marker of ["CHECKLIST_STATE_JSON:", "NOTES_STATE_JSON:", "TABLES_STATE_JSON:"]) {
      expect(bundle).toContain(marker);
    }
    expect(bundle).toContain("Taylor");
    expect(bundle).toContain("Hold until follow-ups are resolved.");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    const waiting = page.waitForEvent("download");
    await clickSidebarExport(page, "#btnSaveHtml");
    const download = await waiting;
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh-controls-"));
    try {
      const out = path.join(dir, "controls-export.html");
      fs.writeFileSync(out, await readDownload(download), "utf8");
      await page.goto(fileUrl(out));
      await ready(page);
      await expect(note).toHaveValue("Hold until follow-ups are resolved.");
      await expect(table.locator('[data-cmh-row="loadtest"] [data-cmh-edit-column="owner"]')).toHaveValue("Taylor");
      await expect(table.locator("tbody tr")).toHaveCount(4);
      await expect(ctrl(page, "rollback")).toHaveAttribute("data-cmh-check-state", "check");
      await expect(page.locator(".cm-card-table, .cm-card-note, .cm-card-checklist")).toHaveCount(0);
      expect(page.__external).toEqual([]);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
}

const LIST = `
  <h1>Checklist demo</h1>
  <div class="cmh-checklist" data-cmh-checklist="release" data-cmh-checklist-label="Release readiness">
    <ul>
      <li data-cmh-item="backend" data-cmh-state="blank">Backend
        <ul>
          <li data-cmh-item="mig" data-cmh-state="check">Migrations applied</li>
          <li data-cmh-item="load" data-cmh-state="check">Load test green</li>
        </ul>
      </li>
      <li data-cmh-item="rel" data-cmh-state="blank">Release notes</li>
    </ul>
  </div>
  <p id="after">Trailing prose after the checklist.</p>`;

const TABLE = `
  <h1>Audit</h1>
  <p id="before">Leading prose before the checklist.</p>
  <table class="cmh-checklist" data-cmh-checklist="audit" data-cmh-checklist-label="Security audit">
    <thead><tr><th></th><th>Control</th></tr></thead>
    <tbody>
      <tr data-cmh-item="net" data-cmh-state="blank"><td class="st"></td><td>Network</td></tr>
      <tr data-cmh-item="fw" data-cmh-parent="net" data-cmh-state="check"><td></td><td>Firewall</td></tr>
      <tr data-cmh-item="tls" data-cmh-parent="net" data-cmh-state="cross"><td></td><td>TLS enforced</td></tr>
    </tbody>
  </table>`;

async function open(page, content, key) {
  await installClipboardCapture(page);
  const { html } = stageContent(content, { key });
  await page.goto(fileUrl(html));
  await ready(page);
  return html;
}

// The injected four-state control for an item, located by the item's stable id.
const ctrl = (page, item) => page.locator(`[data-cmh-item="${item}"] .cmh-check`).first();
const stateOf = (page, item) => ctrl(page, item).getAttribute("data-cmh-check-state");

test("CMH-CHECK-01: authored checklist renders controls; leaf vs branch detected", async ({ page }) => {
  await open(page, LIST, "cmh-check-01");
  await expect(page.locator(".cmh-checklist.cmh-checklist-ready")).toHaveCount(1);
  // Every authored item gets exactly one control.
  await expect(page.locator('[data-cmh-item="backend"] > .cmh-check, [data-cmh-item="backend"] .cmh-check').first()).toBeVisible();
  await expect(ctrl(page, "mig")).toBeVisible();
  await expect(page.locator('[data-cmh-item="backend"]')).toHaveAttribute("data-cmh-check-role", "branch");
  await expect(page.locator('[data-cmh-item="mig"]')).toHaveAttribute("data-cmh-check-role", "leaf");
});

test("CMH-CHECK-02: a leaf cycles blank -> check -> cross -> question -> blank", async ({ page }) => {
  await open(page, LIST, "cmh-check-02");
  expect(await stateOf(page, "rel")).toBe("blank");
  await ctrl(page, "rel").click();
  expect(await stateOf(page, "rel")).toBe("check");
  await ctrl(page, "rel").click();
  expect(await stateOf(page, "rel")).toBe("cross");
  await ctrl(page, "rel").click();
  expect(await stateOf(page, "rel")).toBe("question");
  await ctrl(page, "rel").click();
  expect(await stateOf(page, "rel")).toBe("blank");
});

test("CMH-CHECK-03: a branch aggregates over its direct children (all-same, else mixed)", async ({ page }) => {
  await open(page, LIST, "cmh-check-03");
  // Backend is authored blank but both children are check, so it derives check.
  expect(await stateOf(page, "backend")).toBe("check");
  // In the table, net's children disagree (check vs cross), so it is mixed.
  await open(page, TABLE, "cmh-check-03b");
  expect(await stateOf(page, "net")).toBe("mixed");
  // Make the children agree: cycle firewall check -> cross so both are cross.
  await ctrl(page, "fw").click();
  expect(await stateOf(page, "fw")).toBe("cross");
  expect(await stateOf(page, "net")).toBe("cross");
});

test("CMH-CHECK-04: clicking a branch propagates its next state to all descendant leaves", async ({ page }) => {
  await open(page, LIST, "cmh-check-04");
  expect(await stateOf(page, "backend")).toBe("check"); // derived from children
  await ctrl(page, "backend").click();                  // check -> cross, pushed down
  expect(await stateOf(page, "mig")).toBe("cross");
  expect(await stateOf(page, "load")).toBe("cross");
  expect(await stateOf(page, "backend")).toBe("cross");
});

test("CMH-CHECK-05: only changed leaves persist (minimal delta), restored on reload", async ({ page }) => {
  const html = await open(page, LIST, "cmh-check-05");
  await ctrl(page, "rel").click(); // blank -> check (a real change vs baseline)
  const stored = await page.evaluate(() => {
    const k = document.getElementById("commentRoot").dataset.commentKey + "::cl";
    return JSON.parse(localStorage.getItem(k) || "{}");
  });
  // Exactly one leaf stored: no baseline-equal leaves, no derived parents.
  expect(stored).toEqual({ release: { rel: "v" } });
  await page.goto(fileUrl(html));
  await ready(page);
  expect(await stateOf(page, "rel")).toBe("check");
  // Cycling back to baseline prunes the entry entirely.
  await ctrl(page, "rel").click(); // check -> cross
  await ctrl(page, "rel").click(); // cross -> question
  await ctrl(page, "rel").click(); // question -> blank (== baseline)
  const after = await page.evaluate(() => {
    const k = document.getElementById("commentRoot").dataset.commentKey + "::cl";
    return localStorage.getItem(k);
  });
  expect(after == null || after === "{}").toBeTruthy();
});

test("CMH-CHECK-06: one card per changed list; Reset reverts that list to baseline", async ({ page }) => {
  await open(page, LIST, "cmh-check-06");
  await expect(page.locator(".cm-card-checklist")).toHaveCount(0);
  await ctrl(page, "rel").click();
  const card = page.locator(".cm-card-checklist");
  await expect(card).toHaveCount(1);
  await expect(card).toContainText("Release readiness");
  await expect(card).toContainText("Release notes");
  // jump and reset share casing (both lowercase), and the change record uses a single-character
  // arrow glyph, never a "->" that can wrap onto two lines.
  await expect(card.locator('[data-act="cl-jump"]')).toHaveText("jump");
  await expect(card.locator('[data-act="cl-reset"]')).toHaveText("reset");
  await expect(card.locator(".cmh-cl-arrow")).toHaveText("\u2192");
  await expect(card).not.toContainText("->");
  // The changed checklist is reflected in BOTH counters, so it is not mistaken for no change (issue #643).
  await expect(page.locator("#sidebarCount")).toHaveText("1");
  await expect(page.locator("#toolbarCount")).toHaveText("1");
  await card.locator('[data-act="cl-reset"]').click();
  await expect(page.locator(".cm-card-checklist")).toHaveCount(0);
  expect(await stateOf(page, "rel")).toBe("blank");
  // Reverting the only change returns both counters to 0.
  await expect(page.locator("#sidebarCount")).toHaveText("0");
  await expect(page.locator("#toolbarCount")).toHaveText("0");
});

test("CMH-CHECK-07: the checklist card is placed by document order among comments", async ({ page }) => {
  await open(page, TABLE, "cmh-check-07");
  // A comment on prose that sits BEFORE the checklist in the document.
  await addTextComment(page, "#before", "before note");
  await ctrl(page, "fw").click(); // create a checklist change so the card exists
  const order = await page.$$eval("#commentList > article", (els) =>
    els.map((e) => e.classList.contains("cm-card-checklist") ? "CHECKLIST" : (e.querySelector(".note") || {}).textContent));
  const beforeIdx = order.indexOf("before note");
  const clIdx = order.indexOf("CHECKLIST");
  expect(beforeIdx).toBeGreaterThanOrEqual(0);
  expect(clIdx).toBeGreaterThan(beforeIdx); // the checklist (after #before) sorts after that comment
});

test("CMH-CHECK-08: Copy all includes a checklist section and CHECKLIST_STATE_JSON", async ({ page }) => {
  await open(page, TABLE, "cmh-check-08");
  await ctrl(page, "fw").click(); // check -> cross
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toContain('## Checklist "audit"');
  expect(bundle).toContain("Firewall");
  expect(bundle).toContain("check -> cross");
  expect(bundle).toContain('CHECKLIST_STATE_JSON: {"audit":{"fw":"cross"}}');
});

test("CMH-CHECK-09: export bakes current states into data-cmh-state", async ({ page }) => {
  await open(page, LIST, "cmh-check-09");
  await ctrl(page, "rel").click(); // blank -> check
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnSaveHtml"),
  ]);
  const html = await readDownload(download);
  expect(html).toMatch(/data-cmh-item="rel"[^>]*data-cmh-state="check"|data-cmh-state="check"[^>]*data-cmh-item="rel"/);
});

test("CMH-CHECK-10: table-shape parent links build the tree; aggregation and propagation work", async ({ page }) => {
  await open(page, TABLE, "cmh-check-10");
  await expect(page.locator('[data-cmh-item="net"]')).toHaveAttribute("data-cmh-check-role", "branch");
  await ctrl(page, "net").click(); // mixed -> check, pushed to fw + tls
  expect(await stateOf(page, "fw")).toBe("check");
  expect(await stateOf(page, "tls")).toBe("check");
  expect(await stateOf(page, "net")).toBe("check");
});

test("CMH-CHECK-11: item labels stay text-commentable; the control is cm-skip", async ({ page }) => {
  await open(page, LIST, "cmh-check-11");
  await expect(ctrl(page, "rel")).toHaveClass(/cm-skip/);
  await addTextComment(page, '[data-cmh-item="rel"]', "note on the label");
  await expect(page.locator("mark.cm-hl")).toHaveCount(1);
  await expect(page.locator("#sidebarCount")).toHaveText("1");
});

test("CMH-CHECK-12: keyboard cycles the control and ARIA announces the state", async ({ page }) => {
  await open(page, LIST, "cmh-check-12");
  const c = ctrl(page, "rel");
  await expect(c).toHaveAttribute("aria-label", /Release notes/);
  await c.focus();
  await page.keyboard.press("Enter");
  expect(await stateOf(page, "rel")).toBe("check");
  await expect(c).toHaveAttribute("aria-label", /check/i);
  await page.keyboard.press(" ");
  expect(await stateOf(page, "rel")).toBe("cross");
});

test("CMH-CHECK-BADGE: an unsaved checklist change flips the badge to Not shareable", async ({ page }) => {
  await open(page, LIST, "cmh-check-badge");
  await expect(page.locator("#cmTypeBadge")).toHaveText("Shareable");
  await ctrl(page, "rel").click();
  await expect(page.locator("#cmTypeBadge")).toHaveText("Not shareable");
  const reason = await page.getAttribute("#cmTypeBadge", "title");
  expect(reason).toContain("checklist");
});

test("CMH-CHECK-16: a table item's label is its first content cell, not every other cell", async ({ page }) => {
  const T = `
    <table class="cmh-checklist" data-cmh-checklist="own" data-cmh-checklist-label="Owned">
      <thead><tr><th></th><th>Control</th><th>Owner</th></tr></thead>
      <tbody><tr data-cmh-item="a" data-cmh-state="blank"><td></td><td>Rotate signing keys</td><td>Priya</td></tr></tbody>
    </table>`;
  await open(page, T, "cmh-check-16");
  await ctrl(page, "a").click();
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  expect(bundle).toContain('[a] "Rotate signing keys":');
  expect(bundle).not.toContain("Rotate signing keys Priya"); // the Owner cell is not part of the label
});

test("CMH-CHECK-17: a checklist that loads with a persisted change opens the sidebar so the card is seen", async ({ page }) => {
  await installClipboardCapture(page);
  const key = "cmh-check-17";
  // Seed a persisted leaf change (rel: blank -> check) BEFORE the page's scripts run, so the
  // document loads already having a checklist change - the case where a toggle never fires the
  // 0 -> >0 transition, so the sidebar must open at startup instead.
  await page.addInitScript((k) => { localStorage.setItem(k + "::cl", JSON.stringify({ release: { rel: "v" } })); }, key);
  const { html } = stageContent(LIST, { key });
  await page.goto(fileUrl(html));
  await ready(page);
  await expect(page.locator("body")).toHaveClass(/sidebar-open/);
  const card = page.locator(".cm-card-checklist");
  await expect(card).toHaveCount(1);
  await expect(card).toBeVisible();
});

test("CMH-CHECK-18: Clear restores checklist state changes to the authored baseline", async ({ page }) => {
  await open(page, LIST, "cmh-check-18");
  await ctrl(page, "rel").click();
  await expect(page.locator(".cm-card-checklist")).toHaveCount(1);
  expect(await stateOf(page, "rel")).toBe("check");

  await clickClearAll(page);
  await page.locator(".cm-modal .danger").click();
  await expect(page.locator(".cm-card-checklist")).toHaveCount(0);
  expect(await stateOf(page, "rel")).toBe("blank");
  const stored = await page.evaluate(() => {
    const k = document.getElementById("commentRoot").dataset.commentKey + "::cl";
    return localStorage.getItem(k);
  });
  expect(stored).toBeNull();
});

test("CMH-DEMO-04: the shipped checklist demo renders both shapes, aggregates, and persists a toggle", async ({ page }) => {
  await installClipboardCapture(page);
  await routeExampleLibsLocal(page);
  await page.goto(fileUrl(CHECKLIST_DEMO));
  await ready(page);
  // Both the nested-list and the table checklist are wired up.
  await expect(page.locator(".cmh-checklist.cmh-checklist-ready")).toHaveCount(2);
  // The "Backend" branch aggregates its authored children (check / cross / question) to mixed.
  await expect(ctrl(page, "backend")).toHaveAttribute("data-cmh-check-state", "mixed");
  // Toggling a leaf persists across a reload of the same file.
  await ctrl(page, "rollback").click(); // blank -> check
  await expect(ctrl(page, "rollback")).toHaveAttribute("data-cmh-check-state", "check");
  await page.goto(fileUrl(CHECKLIST_DEMO));
  await ready(page);
  await expect(ctrl(page, "rollback")).toHaveAttribute("data-cmh-check-state", "check");
});

const PROTO = `
  <h1>Proto pollution probe</h1>
  <div class="cmh-checklist" data-cmh-checklist="__proto__" data-cmh-checklist-label="Proto probe">
    <ul>
      <li data-cmh-item="polluted" data-cmh-state="blank">Ordinary item keyed "polluted"</li>
    </ul>
  </div>
  <div class="cmh-checklist" data-cmh-checklist="constructor" data-cmh-checklist-label="Constructor probe">
    <ul>
      <li data-cmh-item="polluted2" data-cmh-state="blank">Ordinary item keyed "polluted2"</li>
    </ul>
  </div>`;

test("CMH-SEC-02: cycling checklists authored with id __proto__ or constructor cannot pollute Object.prototype", async ({ page }) => {
  await open(page, PROTO, "cmh-sec-02-click");
  // A checklist id of "__proto__" or "constructor" still works as ordinary data: no
  // reserved-key skip, so both items render and cycle normally - this is document-reachable via
  // a plain user click, no localStorage seeding needed.
  expect(await stateOf(page, "polluted")).toBe("blank");
  expect(await stateOf(page, "polluted2")).toBe("blank");
  await ctrl(page, "polluted").click();
  await ctrl(page, "polluted2").click();
  expect(await stateOf(page, "polluted")).toBe("check");
  expect(await stateOf(page, "polluted2")).toBe("check");
  // The historical bug: a plain {} makes `_clOverrides["__proto__"]` (or ["constructor"])
  // resolve to Object.prototype (or Object) itself (truthy, so the create-guard is skipped),
  // and writing item.key onto it lands a new "polluted"/"polluted2" property on every object,
  // or overwrites the shared Object constructor. Assert neither happened.
  expect(await page.evaluate(() => ({}).polluted)).toBeUndefined();
  expect(await page.evaluate(() => ({}).polluted2)).toBeUndefined();
  expect(await page.evaluate(() => Object.prototype.hasOwnProperty.call({}, "polluted"))).toBe(false);
  expect(await page.evaluate(() => Object.prototype.constructor === Object)).toBe(true);
});

test("CMH-SEC-02: a crafted ::cl localStorage payload with __proto__ and constructor keys cannot pollute Object.prototype", async ({ page }) => {
  const key = "cmh-sec-02-storage";
  // JSON.parse (unlike an object literal) creates a real OWN "__proto__" property via
  // CreateDataProperty, so this mirrors an attacker crafting the persisted "::cl" JSON
  // directly: data["__proto__"] resolves the crafted inner map, not Object.prototype, on the
  // way in, and data["constructor"] resolves the crafted inner map, not Object. The
  // "release"/"rel" entry additionally corrupts the stored *code* to "__proto__", and
  // "release"/"mig" corrupts its code to "constructor" - both used to make the token lookup
  // itself resolve to a truthy prototype/constructor object.
  await page.addInitScript((k) => {
    localStorage.setItem(k + "::cl",
      '{"__proto__":{"polluted":"v"},"constructor":{"polluted2":"v"},'
      + '"release":{"rel":"__proto__","mig":"constructor"}}');
  }, key);
  await open(page, LIST, key);
  expect(await page.evaluate(() => ({}).polluted)).toBeUndefined();
  expect(await page.evaluate(() => ({}).polluted2)).toBeUndefined();
  expect(await page.evaluate(() => Object.prototype.hasOwnProperty.call({}, "polluted"))).toBe(false);
  expect(await page.evaluate(() => Object.prototype.constructor === Object)).toBe(true);
  // The corrupted "rel"/"mig" codes are not recognized tokens, so they are ignored and both
  // items fall back to their authored baseline instead of rendering the stringified
  // prototype/constructor object.
  expect(await stateOf(page, "rel")).toBe("blank");
  expect(await stateOf(page, "mig")).toBe("check");
});
