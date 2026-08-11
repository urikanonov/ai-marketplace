// Generated-DOM identity dedupe (tools/authoring/dom_slim.py): a checklist item's identity is
// stored ONCE and derived, rather than written on every row. The document a reader opens must be
// indistinguishable from the untrimmed one - same render, same keyboard behavior, same comment
// threads, same checklist state - so every test drives the two side by side, with the trimmed one
// produced by the REAL tool at test time.
import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import {
  PYTHON, SKILL, fileUrl, ready, stageContent, installClipboardCapture,
  clickSidebarExport, readDownload, storedComments, addTextComment,
} from "./helpers.js";

const SLIM = path.join(SKILL, "tools", "authoring", "dom_slim.py");

const CONTENT = `
  <h1>Trim demo</h1>
  <div class="cmh-checklist" data-cmh-checklist="release" data-cmh-checklist-label="Release readiness">
    <ul>
      <li data-rdc-id="backend" data-cmh-item="backend">Backend
        <ul>
          <li data-rdc-id="mig" data-cmh-item="mig" data-cmh-state="check">Migrations applied</li>
          <li data-rdc-id="load" data-cmh-item="load" data-cmh-state="check">Load test green</li>
        </ul>
      </li>
      <li data-rdc-id="docs" data-cmh-item="docs" data-cmh-state="blank">Docs updated</li>
    </ul>
  </div>
  <table class="cmh-checklist" data-cmh-checklist="audit" data-cmh-checklist-label="Security audit">
    <tbody>
      <tr data-rdc-id="net" data-cmh-item="net"><td></td><td>Network</td></tr>
      <tr data-rdc-id="fw" data-rdc-parent="net" data-cmh-item="fw" data-cmh-parent="net" data-cmh-state="check"><td></td><td>Firewall</td></tr>
      <tr data-rdc-id="tls" data-rdc-parent="net" data-cmh-item="tls" data-cmh-parent="net" data-cmh-state="check"><td></td><td>TLS enforced</td></tr>
    </tbody>
  </table>
  <p id="prose">Some prose that a reviewer can comment on in this document.</p>
  <button id="save" type="button" aria-label="Save draft">Save draft</button>`;

// The trimmed document is produced by the REAL tool from the untrimmed one, so these tests
// exercise what finalize actually writes rather than a hand-written approximation of it.
function stagePair(key) {
  const authored = stageContent(CONTENT, { key: `${key}-authored` });
  const trimmed = stageContent(CONTENT, { key: `${key}-trimmed` });
  execFileSync(PYTHON, [SLIM, trimmed.html], { cwd: SKILL, stdio: "pipe" });
  const text = fs.readFileSync(trimmed.html, "utf8");
  if (!text.includes('data-cmh-item-attr="data-rdc-id"')) throw new Error("dom_slim trimmed nothing");
  return { authored, trimmed };
}

async function open(page, staged) {
  await installClipboardCapture(page);
  await page.goto(fileUrl(staged.html));
  await ready(page);
}

// Locate an item by the identity that survives the trim, so one selector serves both documents.
const item = (page, id) => page.locator(`[data-rdc-id="${id}"]`).first();
const ctrl = (page, id) => item(page, id).locator(".cmh-check").first();
const stateOf = (page, id) => ctrl(page, id).getAttribute("data-cmh-check-state");

// Everything a reader can see about the content, with the attribute the trim removes left out:
// the element structure, the rendered text, the box, and the resolved paint.
const snapshot = (page) => page.evaluate(() => {
  const out = [];
  document.getElementById("commentRoot").querySelectorAll("*").forEach((el) => {
    if (el.closest(".cm-skip") || el.tagName === "STYLE" || el.tagName === "SCRIPT") return;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    out.push([
      el.tagName,
      (el.textContent || "").replace(/\s+/g, " ").trim(),
      cs.color, cs.backgroundColor, cs.fontWeight, cs.display,
      Math.round(r.width), Math.round(r.height),
    ].join("|"));
  });
  return out;
});

test("CMH-SIZE-02: a trimmed checklist derives the same identity, states and storage as the authored one", async ({ page }) => {
  test.slow();
  const { authored, trimmed } = stagePair("slim1");

  await open(page, authored);
  await ctrl(page, "docs").click();
  await ctrl(page, "mig").click();
  const before = await page.evaluate((k) => localStorage.getItem(k + "::cl"), "slim1-authored");

  await open(page, trimmed);
  // The duplicated copy really is gone from the file the reader opens.
  await expect(page.locator("#commentRoot [data-cmh-item]")).toHaveCount(0);
  await expect(page.locator('[data-cmh-checklist="release"]')).toHaveAttribute(
    "data-cmh-item-attr", "data-rdc-id");
  await expect(item(page, "backend")).toHaveAttribute("data-cmh-check-role", "branch");
  await expect(item(page, "docs")).toHaveAttribute("data-cmh-check-role", "leaf");
  await ctrl(page, "docs").click();
  await ctrl(page, "mig").click();
  const after = await page.evaluate((k) => localStorage.getItem(k + "::cl"), "slim1-trimmed");

  // Identical stored keys and codes: the identity was derived, not renamed.
  expect(JSON.parse(after)).toEqual(JSON.parse(before));
});

test("CMH-SIZE-02: the derived parent link still aggregates, propagates and bakes into an export", async ({ page }) => {
  test.slow();
  const { trimmed } = stagePair("slim2");
  await open(page, trimmed);
  await expect(item(page, "net")).toHaveAttribute("data-cmh-check-role", "branch");
  expect(await stateOf(page, "net")).toBe("check");   // aggregated from fw + tls
  await ctrl(page, "net").click();                    // check -> cross, pushed down
  expect(await stateOf(page, "fw")).toBe("cross");
  expect(await stateOf(page, "tls")).toBe("cross");

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnSaveHtml"),
  ]);
  const html = await readDownload(download);
  expect(html).toMatch(/data-rdc-id="tls"[^>]*data-cmh-state="cross"|data-cmh-state="cross"[^>]*data-rdc-id="tls"/);
  expect(html).not.toContain('data-cmh-item="tls"');
});

test("CMH-SIZE-03: a trimmed document renders identically and announces the same names", async ({ page }) => {
  test.slow();
  const { authored, trimmed } = stagePair("slim3");
  await open(page, authored);
  const before = await snapshot(page);
  await expect(page.locator("#save")).toHaveAccessibleName("Save draft");

  await open(page, trimmed);
  const after = await snapshot(page);

  expect(after).toEqual(before);
  expect(before.length).toBeGreaterThan(10);
  // The label transform was removed after review measured that removing an aria-label empties
  // the accessible name on every element whose implicit role is not name-from-content.
  await expect(page.locator("#save")).toHaveAttribute("aria-label", "Save draft");
  await expect(page.locator("#save")).toHaveAccessibleName("Save draft");
});

test("CMH-SIZE-03: keyboard cycling and the announced state survive the trim", async ({ page }) => {
  test.slow();
  const { trimmed } = stagePair("slim4");
  await open(page, trimmed);
  await ctrl(page, "docs").focus();
  await page.keyboard.press("Enter");
  expect(await stateOf(page, "docs")).toBe("check");
  await expect(ctrl(page, "docs")).toHaveAttribute("aria-label", /Docs updated: check/);
  await page.keyboard.press(" ");
  expect(await stateOf(page, "docs")).toBe("cross");
});

test("CMH-SIZE-03: a document written before the trim comments, exports and reopens with identical thread state", async ({ page }) => {
  test.slow();
  // The backwards-compatibility case: an UNTRIMMED document, byte for byte as an older version
  // wrote it, opened under the runtime that now derives identity.
  const authored = stageContent(CONTENT, { key: "slim5" });
  await open(page, authored);
  await ctrl(page, "docs").click();
  await addTextComment(page, "#prose", "a note that must survive the round trip");
  await expect(page.locator("mark.cm-hl")).toHaveCount(1);
  const threads = await storedComments(page);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnSaveHtml"),
  ]);
  const exported = path.join(authored.dir, "reopened.html");
  fs.writeFileSync(exported, await readDownload(download));

  await page.goto(fileUrl(exported));
  await ready(page);
  await expect(page.locator("mark.cm-hl")).toHaveCount(1);
  await expect(page.locator(".cm-card").filter({ hasText: "a note that must survive the round trip" }))
    .toHaveCount(1);
  // The authored identity is still spelled the old way, and the checklist state came back with it.
  await expect(page.locator('#commentRoot [data-cmh-item="docs"]')).toHaveCount(1);
  expect(await stateOf(page, "docs")).toBe("check");
  const reopened = await storedComments(page);
  expect(reopened.map((c) => [c.id, c.note, c.start, c.end]))
    .toEqual(threads.map((c) => [c.id, c.note, c.start, c.end]));
});
