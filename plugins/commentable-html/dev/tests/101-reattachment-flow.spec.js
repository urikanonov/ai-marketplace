import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { gunzipSync } from "zlib";
import {
  DEV, EXAMPLES, stageContent, fileUrl, ready, denyExternalNetwork, installClipboardCapture,
  clickSidebarExport, readDownload, lastCopied, openSearch, routeExampleLibsLocal,
} from "./helpers.js";

const INITIAL = '<section><h2 id="risk-heading">Risks</h2>'
  + '<p id="change">Replace this opening sentence.</p>'
  + '<p id="question">The recovery budget remains twenty minutes.</p></section>';
const dirs = new Set();

function fixture(content = INITIAL) {
  const staged = stageContent(content, { key: "cmh-reattach-flow", source: "review.html" });
  dirs.add(staged.dir);
  return staged;
}

function revise(staged, content, handled = []) {
  const html = fs.readFileSync(staged.html, "utf8")
    .replace(/(<!-- BEGIN: commentable-html - CONTENT[^>]*-->)[\s\S]*?(<!-- END: commentable-html - CONTENT -->)/,
      (_m, a, b) => a + "\n" + content + "\n" + b)
    .replace(/(<script[^>]*\bid="handledCommentIds"[^>]*>)[\s\S]*?(<\/script>)/,
      (_m, a, b) => a + JSON.stringify(handled) + b);
  fs.writeFileSync(staged.html, html);
}

async function select(page, selector, quote) {
  await page.locator(selector).scrollIntoViewIfNeeded();
  await page.evaluate(({ selector, quote }) => {
    const el = document.querySelector(selector);
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let n;
    while ((n = walker.nextNode())) nodes.push(n);
    const text = nodes.map(n => n.data).join("");
    const start = quote == null ? 0 : text.indexOf(quote);
    if (start < 0) throw new Error("selection quote missing");
    const end = start + (quote == null ? text.length : quote.length);
    const range = document.createRange();
    let at = 0;
    for (const node of nodes) {
      if (start >= at && start < at + node.data.length) range.setStart(node, start - at);
      if (end > at && end <= at + node.data.length) { range.setEnd(node, end - at); break; }
      at += node.data.length;
    }
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 80, clientY: 80 }));
  }, { selector, quote });
  await expect(page.locator("#contextMenu")).toBeVisible();
}

async function comment(page, selector, note, quote, purpose) {
  await select(page, selector, quote);
  await page.locator("#menuComment").click();
  const composer = page.locator(".cm-composer").last();
  if (purpose) await composer.locator(".cm-purpose-control select").selectOption(purpose);
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toHaveCount(0);
  return page.locator(".cm-card").filter({ hasText: note }).getAttribute("data-cid");
}

async function exportHtml(page) {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnSaveHtml"),
  ]);
  return readDownload(download);
}

function embedded(html) {
  const block = html.match(/<script[^>]*\bid="embeddedComments"[^>]*>([\s\S]*?)<\/script>/);
  if (!block) throw new Error("embedded comment block missing");
  return JSON.parse(block[1]);
}

async function open(page, staged) {
  await page.goto(fileUrl(staged.html));
  await ready(page);
}

test.beforeEach(async ({ page }) => {
  await denyExternalNetwork(page);
  await installClipboardCapture(page);
  await page.addInitScript(() => localStorage.setItem("cmh::author", "Reviewer"));
});

test.afterEach(() => {
  for (const dir of dirs) fs.rmSync(dir, { recursive: true, force: true });
  dirs.clear();
});

test("only handled comments disappear and unsent questions follow revised content (CMH-REATTACH-10)", async ({ page }) => {
  const staged = fixture();
  await open(page, staged);
  const handled = await comment(page, "#change", "Rewrite the introduction.");
  const remaining = await comment(page, "#question", "Why twenty minutes?");
  await page.locator(`.cm-card[data-cid="${handled}"] [data-act="copy"]`).click();
  const sent = await lastCopied(page);
  expect(sent).toContain("Rewrite the introduction.");
  expect(sent).not.toContain("Why twenty minutes?");
  revise(staged, INITIAL.replace("Replace this opening sentence.", "A much longer introduction. ".repeat(12)), [handled]);
  await page.reload();
  await ready(page);
  await expect(page.locator(`.cm-card[data-cid="${handled}"]`)).toHaveCount(0);
  await expect(page.locator(`#question mark[data-cid="${remaining}"]`)).toHaveText("The recovery budget remains twenty minutes.");
  await expect(page.locator(".cm-card-detached")).toHaveCount(0);
  expect(embedded(await exportHtml(page)).map(c => c.id)).toEqual([remaining]);
});

test("comments added on the displayed old revision while an agent edits survive two refreshes (CMH-REATTACH-11)", async ({ page }) => {
  const staged = fixture();
  await open(page, staged);
  const first = await comment(page, "#change", "Work on this first.");
  revise(staged, INITIAL.replace("Replace this opening sentence.", "The agent has changed this introduction. ".repeat(8)), [first]);
  const late = await comment(page, "#question", "I added this after the agent started.");
  await expect(page.locator("#change")).toHaveText("Replace this opening sentence.");
  await page.reload();
  await ready(page);
  await expect(page.locator(`#question mark[data-cid="${late}"]`)).toHaveText("The recovery budget remains twenty minutes.");
  revise(staged, '<p>Another revision adds material before the report.</p>'.repeat(5)
    + INITIAL.replace("Replace this opening sentence.", "Third introduction."), [first]);
  await page.reload();
  await ready(page);
  await expect(page.locator(`#question mark[data-cid="${late}"]`)).toHaveText("The recovery budget remains twenty minutes.");
  await expect(page.locator(".cm-card")).toHaveCount(1);
});

test("deleted anchors are Detached with searchable copyable threads and recover on later revisions (CMH-REATTACH-12)", async ({ page }) => {
  const staged = fixture();
  await open(page, staged);
  const id = await comment(page, "#question", "Keep this unanswered question.");
  await page.locator(`.cm-card[data-cid="${id}"] [data-act="reply"]`).click();
  const reply = page.locator(".cm-reply-compose");
  await reply.locator("textarea").fill("Additional context from the reviewer.");
  await reply.locator(".cm-reply-save").click();
  revise(staged, INITIAL.replace('<p id="question">The recovery budget remains twenty minutes.</p>',
    '<p id="replacement">An entirely unrelated paragraph about billing and invoices.</p>'));
  await page.reload();
  await ready(page);
  const card = page.locator(`.cm-card[data-cid="${id}"]`);
  await expect(card).toHaveClass(/cm-card-detached/);
  await expect(card.locator(".cm-detached-status")).toHaveText(/Detached/);
  await expect(page.locator(`mark[data-cid="${id}"]`)).toHaveCount(0);
  await expect(card.locator(".quote")).toContainText("The recovery budget remains twenty minutes.");
  await expect(card.locator(".cm-reply")).toContainText("Additional context from the reviewer.");
  await openSearch(page);
  await page.locator("#cmSearchInput").fill("unanswered");
  await expect(card).toBeVisible();
  await card.locator('[data-act="copy"]').click();
  const copied = await lastCopied(page);
  expect(copied).toContain("Attachment: Detached");
  expect(copied).toContain("Additional context from the reviewer.");
  await page.locator("#cmSearchInput").fill("");
  await page.reload();
  await ready(page);
  await expect(card).toHaveClass(/cm-card-detached/);
  revise(staged, '<p>New introductory material.</p>' + INITIAL);
  await page.reload();
  await ready(page);
  await expect(page.locator(`#question mark[data-cid="${id}"]`)).toHaveText("The recovery budget remains twenty minutes.");
  await expect(card).not.toHaveClass(/cm-card-detached/);
});

test("manual reattachment changes only the anchor and preserves the original thread across reload (CMH-REATTACH-13)", async ({ page }) => {
  const staged = fixture();
  await open(page, staged);
  const id = await comment(page, "#question", "Keep the review text unchanged.");
  const before = embedded(await exportHtml(page))[0];
  revise(staged, '<section><h2>New risks</h2><p id="new-target">Recovery now has a completely different policy.</p></section>');
  await page.reload();
  await ready(page);
  const card = page.locator(`.cm-card[data-cid="${id}"]`);
  await expect(card).toHaveClass(/cm-card-detached/);
  await card.getByRole("button", { name: "Reattach", exact: true }).click();
  await expect(page.locator(".cm-reattach-prompt")).toBeVisible();
  await select(page, "#new-target", "a completely different policy");
  await expect(page.locator("#menuComment")).toHaveText("Attach comment");
  await page.locator("#menuComment").click();
  await expect(page.locator(`#new-target mark[data-cid="${id}"]`)).toHaveText("a completely different policy");
  await expect(page.locator(".cm-reattach-prompt")).toHaveCount(0);
  const after = embedded(await exportHtml(page))[0];
  expect(after.id).toBe(before.id);
  expect(after.note).toBe(before.note);
  expect(after.createdAt).toBe(before.createdAt);
  expect(after.updatedAt).toBe(before.updatedAt);
  expect(after.quote).toBe("a completely different policy");
  await page.reload();
  await ready(page);
  await expect(page.locator(`#new-target mark[data-cid="${id}"]`)).toHaveText("a completely different policy");
  await expect(card).not.toHaveClass(/cm-card-detached/);
});

test("reattachment can be cancelled and overlapping selections do not lose the Detached comment (CMH-REATTACH-14)", async ({ page }) => {
  const staged = fixture();
  await open(page, staged);
  const id = await comment(page, "#question", "Detached question.");
  const other = await comment(page, "#change", "Existing attached comment.");
  revise(staged, INITIAL.replace('<p id="question">The recovery budget remains twenty minutes.</p>', ""));
  await page.reload();
  await ready(page);
  const card = page.locator(`.cm-card[data-cid="${id}"]`);
  await card.getByRole("button", { name: "Reattach", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(page.locator(".cm-reattach-prompt")).toHaveCount(0);
  await expect(card).toHaveClass(/cm-card-detached/);
  await card.getByRole("button", { name: "Reattach", exact: true }).click();
  await select(page, "#change");
  await page.locator("#menuComment").click();
  await expect(card).toHaveClass(/cm-card-detached/);
  await expect(page.locator(`#change mark[data-cid="${other}"]`)).toHaveText("Replace this opening sentence.");
  await expect(page.locator(`mark[data-cid="${id}"]`)).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel reattachment" }).click();
});

test("Shareable exports carry Detached recovery evidence into a browser without local storage (CMH-REATTACH-15)", async ({ page, browser }) => {
  const staged = fixture();
  await open(page, staged);
  const id = await comment(page, "#question", "Portable detached question.");
  revise(staged, "<p>Only an unrelated report survives.</p>");
  await page.reload();
  await ready(page);
  const html = await exportHtml(page);
  const data = embedded(html);
  expect(data[0].detached).toBe(true);
  expect(data[0].cmAnchor).toBeTruthy();
  const saved = path.join(staged.dir, "shared.html");
  fs.writeFileSync(saved, html);
  const context = await browser.newContext();
  const recipient = await context.newPage();
  try {
    await denyExternalNetwork(recipient);
    await recipient.goto(fileUrl(saved));
    await ready(recipient);
    await expect(recipient.locator(`.cm-card[data-cid="${id}"]`)).toHaveClass(/cm-card-detached/);
    revise({ html: saved }, '<p>New lead.</p>' + INITIAL);
    await recipient.reload();
    await ready(recipient);
    await expect(recipient.locator(`#question mark[data-cid="${id}"]`)).toHaveText("The recovery budget remains twenty minutes.");
  } finally {
    await context.close();
  }
});

test("the previous runtime reads migrated attached and Detached exports without incorrect highlights or lost notes (CMH-REATTACH-16)", async ({ page, browser }) => {
  const staged = fixture();
  await open(page, staged);
  const detached = await comment(page, "#question", "Old runtime must keep this note.");
  const attached = await comment(page, "#change", "Old runtime must highlight this note correctly.");
  revise(staged, '<p>A new lead shifts every offset.</p>'
    + INITIAL.replace('<p id="question">The recovery budget remains twenty minutes.</p>', ""));
  await page.reload();
  await ready(page);
  let html = await exportHtml(page);
  const legacy = gunzipSync(fs.readFileSync(path.join(DEV, "tests", "fixtures", "legacy-offset-runtime.js.gz"))).toString("utf8");
  html = html.replace(/(BEGIN: commentable-html - JS[\s\S]*?-->\s*<script>)[\s\S]*?(<\/script>)/,
    (_m, start, end) => start + "\n" + legacy + "\n" + end);
  expect(html).toContain(legacy);
  const saved = path.join(staged.dir, "old-runtime.html");
  fs.writeFileSync(saved, html);
  const context = await browser.newContext();
  const old = await context.newPage();
  try {
    await denyExternalNetwork(old);
    await old.goto(fileUrl(saved));
    await ready(old);
    await expect(old.locator(".cm-card")).toHaveCount(2);
    await expect(old.locator(`#change mark[data-cid="${attached}"]`)).toHaveText("Replace this opening sentence.");
    await expect(old.locator(`mark[data-cid="${detached}"]`)).toHaveCount(0);
    await expect(old.locator(`.cm-card[data-cid="${detached}"] .note`)).toContainText("Old runtime must keep this note.");
    await old.locator(`.cm-card[data-cid="${detached}"] [data-act="edit"]`).click();
    await old.locator(".cm-reply-compose textarea").fill("Edited safely in the older runtime.");
    await old.locator(".cm-reply-save").click();
    const oldData = embedded(await exportHtml(old));
    const preserved = oldData.find(c => c.id === detached);
    expect(preserved.cmAnchor).toEqual(embedded(html).find(c => c.id === detached).cmAnchor);
    expect(preserved.detached).toBe(true);
    expect(preserved.note).toBe("Edited safely in the older runtime.");
  } finally {
    await context.close();
  }
});

test("sorted-table exports preserve canonical attachment metadata without mutating the live anchor (CMH-REATTACH-17)", async ({ page, browser }) => {
  const staged = fixture('<h2>Service budgets</h2><table><thead><tr><th>Service</th><th>Budget</th></tr></thead>'
    + '<tbody><tr><td>Zeta</td><td id="budget">Twenty minutes</td></tr>'
    + '<tr><td>Alpha</td><td>Ten minutes</td></tr></tbody></table>');
  await open(page, staged);
  const id = await comment(page, "#budget", "Check the Zeta budget.");
  await page.locator("th .cmh-sort-ctrl").first().click();
  await expect(page.locator("tbody tr").first()).toContainText("Alpha");
  const html = await exportHtml(page);
  expect(embedded(html)[0].cmAnchor).toBeTruthy();
  await expect(page.locator("tbody tr").first()).toContainText("Alpha");
  await page.reload();
  await ready(page);
  await expect(page.locator(`#budget mark[data-cid="${id}"]`)).toHaveText("Twenty minutes");
  const saved = path.join(staged.dir, "unsorted-export.html");
  fs.writeFileSync(saved, html);
  const context = await browser.newContext();
  const recipient = await context.newPage();
  try {
    await denyExternalNetwork(recipient);
    await recipient.goto(fileUrl(saved));
    await ready(recipient);
    await expect(recipient.locator("tbody tr").first()).toContainText("Zeta");
    await expect(recipient.locator(`#budget mark[data-cid="${id}"]`)).toHaveText("Twenty minutes");
  } finally {
    await context.close();
  }
});

test("the showcase and Help explain both local revision scenarios and demonstrate Detached recovery (CMH-REATTACH-18)", async ({ page }) => {
  await routeExampleLibsLocal(page);
  await page.goto(fileUrl(path.join(EXAMPLES, "deck-showcase.html")));
  await ready(page);
  expect(await page.evaluate(() => window.__cmhDeck.showSlideById("slide-c0a13630"))).toBe(true);
  const slide = page.locator('[data-slide-id="slide-c0a13630"]');
  await expect(slide).toBeVisible();
  await expect(slide).toContainText("Only some comments handled");
  await expect(slide).toContainText("New comments while the agent edits");
  await expect(slide).toContainText("Detached");
  await page.locator(".cmh-deck-mode-toggle").click();
  await page.locator("#btnHelp").click();
  await page.getByRole("searchbox", { name: "Search help" }).fill("Detached");
  const topic = page.locator(".cm-help-topic").filter({ hasText: "Comments across revisions" });
  await expect(topic).toBeVisible();
  await topic.locator("summary").click();
  await expect(topic).toContainText("without sending all comments");
});

test("Markdown and print disclose Detached anchors rather than claiming historical text is a live location (CMH-REATTACH-19)", async ({ page }) => {
  const staged = fixture();
  await open(page, staged);
  await comment(page, "#question", "Preserve this note in every review format.");
  revise(staged, "<p>Completely unrelated report.</p>");
  await page.reload();
  await ready(page);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnExportMd"),
  ]);
  expect(await readDownload(download)).toContain("Attachment: Detached");
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  await expect(page.locator(".cmh-print-comment")).toContainText("Detached");
  await expect(page.locator(".cmh-print-comment")).toContainText("The recovery budget remains twenty minutes.");
  await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
});

test("blocked persistence warns after manual reattachment while export still retains the session anchor (CMH-REATTACH-20)", async ({ page }) => {
  const staged = fixture();
  await open(page, staged);
  const id = await comment(page, "#question", "Keep the recovered session anchor.");
  revise(staged, '<p id="new-target">A completely new recovery policy.</p>');
  await page.reload();
  await ready(page);
  await page.evaluate(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === "cmh-reattach-flow::z") throw new DOMException("Blocked", "SecurityError");
      return original.call(this, key, value);
    };
  });
  await page.locator(`.cm-card[data-cid="${id}"]`).getByRole("button", { name: "Reattach", exact: true }).click();
  await select(page, "#new-target");
  await page.locator("#menuComment").click();
  await expect(page.locator("#toast")).toContainText("NOT saved");
  await expect(page.locator(`#new-target mark[data-cid="${id}"]`)).toHaveText("A completely new recovery policy.");
  expect(embedded(await exportHtml(page))[0].quote).toBe("A completely new recovery policy.");
});

test("manual reattachment remains keyboard-operable and visible on a narrow viewport (CMH-REATTACH-21)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const staged = fixture();
  await open(page, staged);
  const id = await comment(page, "#question", "A narrow-screen detached question.");
  revise(staged, '<p id="new-target">Choose this new location.</p>');
  await page.reload();
  await ready(page);
  const button = page.locator(`.cm-card[data-cid="${id}"]`).getByRole("button", { name: "Reattach", exact: true });
  await button.focus();
  await page.keyboard.press("Enter");
  const prompt = page.locator(".cm-reattach-prompt");
  await expect(prompt).toBeVisible();
  const rect = await prompt.boundingBox();
  expect(rect.x).toBeGreaterThanOrEqual(0);
  expect(rect.x + rect.width).toBeLessThanOrEqual(390);
  const cancel = page.getByRole("button", { name: "Cancel reattachment" });
  await cancel.focus();
  await page.keyboard.press("Enter");
  await expect(prompt).toHaveCount(0);
  await expect(button).toBeFocused();
});

test("automatic and manual relocation preserve discussion request versions and unanswered state (CMH-REATTACH-22)", async ({ page }) => {
  const staged = fixture();
  await open(page, staged);
  const id = await comment(page, "#question", "Why is that recovery policy sufficient?", null, "discussion");
  const before = embedded(await exportHtml(page))[0];
  revise(staged, "<p>New introductory analysis.</p>".repeat(10) + INITIAL);
  await page.reload();
  await ready(page);
  await expect(page.locator(`#question mark[data-cid="${id}"]`)).toHaveText("The recovery budget remains twenty minutes.");
  const relocated = embedded(await exportHtml(page))[0];
  expect(relocated.requestVersion).toBe(before.requestVersion);
  expect(relocated.updatedAt).toBe(before.updatedAt);
  const card = page.locator(`.cm-card[data-cid="${id}"]`);
  await expect(card).toContainText("Awaiting answer");
  revise(staged, '<p id="new-target">A replacement recovery policy.</p>', [id]);
  await page.reload();
  await ready(page);
  await expect(card).toHaveClass(/cm-card-detached/);
  await card.getByRole("button", { name: "Reattach", exact: true }).click();
  await select(page, "#new-target");
  await page.locator("#menuComment").click();
  const reattached = embedded(await exportHtml(page))[0];
  expect(reattached.requestVersion).toBe(before.requestVersion);
  expect(reattached.intent).toBe("question");
  await expect(card).toContainText("Awaiting answer");
});

test("manual reattachment preserves unsupported selector metadata while adopting the selected text (CMH-REATTACH-23)", async ({ page, browser }) => {
  const staged = fixture();
  await open(page, staged);
  const id = await comment(page, "#question", "Keep this imported thread.");
  const html = await exportHtml(page);
  const data = embedded(html);
  const future = { v: 99, opaque: { foreignSelector: "preserve me" }, original: data[0].cmAnchor.original };
  data[0].cmAnchor = future;
  const imported = html.replace(/(<script[^>]*\bid="embeddedComments"[^>]*>)[\s\S]*?(<\/script>)/,
    (_m, a, b) => a + JSON.stringify(data) + b);
  const saved = path.join(staged.dir, "future-selector.html");
  fs.writeFileSync(saved, imported);
  const context = await browser.newContext();
  const recipient = await context.newPage();
  try {
    await denyExternalNetwork(recipient);
    await recipient.goto(fileUrl(saved));
    await ready(recipient);
    const card = recipient.locator(`.cm-card[data-cid="${id}"]`);
    await expect(card).toHaveClass(/cm-card-detached/);
    await card.getByRole("button", { name: "Reattach", exact: true }).click();
    await select(recipient, "#question", "twenty minutes");
    await recipient.locator("#menuComment").click();
    await expect(recipient.locator(`#question mark[data-cid="${id}"]`)).toHaveText("twenty minutes");
    const attached = embedded(await exportHtml(recipient))[0];
    expect(attached.cmAnchor.v).toBe(1);
    expect(attached.cmAnchor.previousSelector).toEqual(future);
    expect(attached.note).toBe(data[0].note);
    expect(attached.createdAt).toBe(data[0].createdAt);
    await recipient.reload();
    await ready(recipient);
    await expect(recipient.locator(`#question mark[data-cid="${id}"]`)).toHaveText("twenty minutes");
  } finally {
    await context.close();
  }
});

test("large recovery metadata cannot produce a compressed store that its own reader rejects (CMH-REATTACH-24)", async ({ page }) => {
  await open(page, fixture());
  const result = await page.evaluate(() => {
    const quote = "x".repeat(4096);
    const arr = Array.from({ length: 500 }, (_, i) => ({
      id: "c" + i.toString(36).padStart(10, "0"), start: 0, end: 4096, quote, note: "Retain this review.",
      cmAnchor: { v: 1, exact: quote, block: { text: quote }, original: { quote } },
    }));
    const json = JSON.stringify(arr);
    const encoded = window.__cmhStorageCodec.encode(json);
    const decoded = window.__cmhStorageCodec.decode(encoded);
    return { chars: json.length, readable: decoded.ok && decoded.json === json };
  });
  expect(result.chars).toBeGreaterThan(8000000);
  expect(result.readable).toBe(true);
});

test("automatic recovery under storage quota failure warns and remains exportable (CMH-REATTACH-25)", async ({ page }) => {
  const staged = fixture();
  await open(page, staged);
  const id = await comment(page, "#question", "Keep this automatic recovery.");
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === "cmh-reattach-flow::z") throw new DOMException("Full", "QuotaExceededError");
      return original.call(this, key, value);
    };
  });
  revise(staged, "<p>A longer introduction changes every following offset.</p>" + INITIAL);
  await page.reload();
  await ready(page);
  await expect(page.locator(`#question mark[data-cid="${id}"]`)).toBeVisible();
  await expect(page.locator("#toast")).toContainText("NOT saved");
  await expect(page.locator("#toast")).toContainText("Shareable");
  const c = embedded(await exportHtml(page)).find(c => c.id === id);
  expect(c.detached).not.toBe(true);
  expect(c.start).toBeGreaterThan(c.cmAnchor.original.start);
});
