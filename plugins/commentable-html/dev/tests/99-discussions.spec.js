import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { spawnSync } from "child_process";
import {
  openComposerFor, addTextComment, storedComments, stageContent, fileUrl, ready,
  installClipboardCapture, lastCopied, expectNoteFenced, machineTrailerBody,
  clickSidebarExport, readDownload, routeExampleLibsLocal, SKILL, PYTHON,
} from "./helpers.js";

const CONTENT = '<h1>Queue design</h1><section><h2 id="retry">Retries</h2>'
  + '<p id="questionAnchor">Each task has at most three attempts.</p>'
  + '<p id="editAnchor">The retry delay is configurable.</p></section>';

async function openDoc(page, key = "discussion-e2e") {
  const staged = stageContent(CONTENT, { key, source: "queue.html" });
  await routeExampleLibsLocal(page);
  await installClipboardCapture(page);
  await page.goto(fileUrl(staged.html));
  await ready(page);
  return staged;
}

async function panel(page) {
  if (!await page.locator("body").evaluate((el) => el.classList.contains("sidebar-open"))) {
    await page.click("#btnToggleSidebar");
  }
}

async function discuss(page, note = "Why use a queue?") {
  const composer = await openComposerFor(page, "#questionAnchor");
  await composer.getByLabel("Comment purpose").selectOption("discussion");
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  return (await storedComments(page)).find((c) => c.note === note.trim());
}

async function reply(page, note, intent = "question") {
  await panel(page);
  await page.locator(".cm-reply-btn").first().click();
  const editor = page.locator(".cm-reply-compose");
  await editor.getByLabel("Reply purpose").selectOption(intent);
  await editor.locator("textarea").fill(note);
  await editor.locator(".cm-reply-save").click();
  return (await storedComments(page)).find((c) => c.note === note);
}

async function copy(page, selector = "#btnCopyAll") {
  await panel(page);
  await page.evaluate(() => {
    window.__discussionCopyFeedback = null;
    const toast = document.getElementById("toast");
    const observer = new MutationObserver(() => {
      if (toast.classList.contains("show") && toast.textContent.startsWith("Copied ")) {
        window.__discussionCopyFeedback = toast.textContent;
        observer.disconnect();
      }
    });
    observer.observe(toast, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
  });
  await page.click(selector);
  await page.waitForFunction(() => window.__discussionCopyFeedback !== null);
  return lastCopied(page);
}

function trailer(bundle, name) {
  const line = machineTrailerBody(bundle).split("\n").find((l) => l.startsWith(name + ": "));
  if (!line) throw new Error("missing " + name);
  return JSON.parse(line.slice(name.length + 2));
}

function runReview(args) {
  const result = spawnSync(PYTHON, [
    path.join(SKILL, "tools", "authoring", "review_threads.py"), ...args,
  ], { encoding: "utf8" });
  expect(result.status, result.stderr).toBe(0);
  return JSON.parse(result.stdout);
}

test("an anchored discussion hands off questions without requesting edits or pruning history (CMH-DISC-01)", async ({ page }) => {
  await openDoc(page);
  const q = await discuss(page);
  expect(q.threadType).toBe("discussion");
  expect(q.intent).toBe("question");
  expect(q.requestVersion).toMatch(/^r[a-f0-9]{32}$/);
  expect(q.start).toBeLessThan(q.end);
  await expect(page.locator(".cm-discussion-status")).toHaveText(/Awaiting answer/);
  const bundle = await copy(page);
  expect(await page.evaluate(() => window.__discussionCopyFeedback)).toContain("Discussion history stays here");
  expect(await page.evaluate(() => window.__discussionCopyFeedback)).not.toContain("marks them handled");
  expect(bundle).toContain("Do not edit the document for questions");
  expect(bundle).not.toContain("apply the edits they request");
  expectNoteFenced(bundle, q.note);
  expect(trailer(bundle, "HANDLED_IDS_JSON")).toEqual([]);
  expect(trailer(bundle, "DISCUSSION_DOCUMENT_JSON")).toEqual({
    key: "discussion-e2e", baseRevision: "", baseSnapshot: [],
  });
  expect(trailer(bundle, "DISCUSSION_REQUESTS_JSON")).toEqual([
    { threadId: q.id, id: q.id, intent: "question", version: q.requestVersion },
  ]);
  await page.reload();
  await ready(page);
  expect((await storedComments(page))[0].threadType).toBe("discussion");
});

test("discussion controls honor the configured theme foreground tokens (CMH-DISC-01)", async ({ page }) => {
  await openDoc(page);
  const composer = await openComposerFor(page, "#questionAnchor");
  const purpose = composer.locator(".cm-purpose-control");
  await purpose.evaluate((el) => el.style.setProperty("--cp-text-muted", "rgb(12, 34, 56)"));
  expect(await purpose.evaluate((el) => getComputedStyle(el).color)).toBe("rgb(12, 34, 56)");
  await composer.getByLabel("Comment purpose").selectOption("discussion");
  await composer.locator("textarea").fill("Why use a queue?");
  await composer.locator('[data-act="save"]').click();
  const kind = page.locator(".cm-message-kind").first();
  await kind.evaluate((el) => el.style.setProperty("--cp-text-muted", "rgb(12, 34, 56)"));
  expect(await kind.evaluate((el) => getComputedStyle(el).color)).toBe("rgb(12, 34, 56)");
});

test("an explicit command reply retains the entire discussion and stays out of legacy handled ids (CMH-DISC-02)", async ({ page }) => {
  await openDoc(page);
  const q = await discuss(page);
  const followup = await reply(page, "What if the worker fails?");
  const command = await reply(page, "Document the retry policy we discussed.", "command");
  await addTextComment(page, "#editAnchor", "Rename delay to backoff.");
  const legacy = (await storedComments(page)).find((c) => c.note === "Rename delay to backoff.");
  const bundle = await copy(page);
  expect(await page.evaluate(() => window.__discussionCopyFeedback)).toContain("Discussion history stays here");
  expect(await page.evaluate(() => window.__discussionCopyFeedback)).toContain("Ordinary edit comments stay until marked handled");
  expectNoteFenced(bundle, q.note);
  expectNoteFenced(bundle, followup.note);
  expectNoteFenced(bundle, command.note);
  expect(bundle).toContain("COMMAND");
  expect(bundle).toContain("entire transcript as context");
  expect(trailer(bundle, "HANDLED_IDS_JSON")).toEqual([legacy.id]);
  expect(trailer(bundle, "DISCUSSION_REQUESTS_JSON").map((r) => r.intent)).toEqual([
    "question", "question", "command",
  ]);
  const selected = await copy(page, `.cm-card[data-cid="${q.id}"] [data-act="copy"]`);
  expect(await page.evaluate(() => window.__discussionCopyFeedback)).toContain("Discussion history stays here");
  expect(await page.evaluate(() => window.__discussionCopyFeedback)).not.toContain("marks it handled");
  expect(trailer(selected, "HANDLED_IDS_JSON")).toEqual([]);
  expect(selected).not.toContain(legacy.note);
  await copy(page, `.cm-card[data-cid="${legacy.id}"] [data-act="copy"]`);
  expect(await page.evaluate(() => window.__discussionCopyFeedback)).toContain("marks it handled");
});

test("an old Copy cannot restore a browser-only discussion deleted in a later export (CMH-DISC-03)", async ({ page }) => {
  const { html, dir } = await openDoc(page, "discussion-deleted-copy");
  page.on("dialog", (dialog) => dialog.accept());
  const q = await discuss(page);
  const bundleFile = path.join(dir, "stale-bundle.txt");
  fs.writeFileSync(bundleFile, await copy(page), "utf8");
  await page.locator(`.cm-card[data-cid="${q.id}"] [data-act="del"]`).click();
  await expect(page.locator(".cm-card[data-cid]")).toHaveCount(0);
  const downloadPromise = page.waitForEvent("download");
  await clickSidebarExport(page, "#btnSaveHtml");
  const exported = await readDownload(await downloadPromise);
  fs.writeFileSync(html, exported, "utf8");
  const before = fs.readFileSync(html);
  const result = spawnSync(PYTHON, [
    path.join(SKILL, "tools", "authoring", "review_threads.py"), "import", html,
    "--bundle-file", bundleFile,
  ], { encoding: "utf8" });
  expect(result.status).not.toBe(0);
  expect(result.stderr).toMatch(/snapshot|stale|changed/);
  expect(fs.readFileSync(html).equals(before)).toBe(true);
  expect(exported).toMatch(/data-cmh-review-revision="r[a-f0-9]{32}"/);
});

test("an owner answer round-trips through the Python tool and a new question reopens the conversation (CMH-DISC-03)", async ({ page }) => {
  const { dir } = await openDoc(page);
  const q = await discuss(page);
  const downloadPromise = page.waitForEvent("download");
  await clickSidebarExport(page, "#btnSaveHtml");
  const exported = await readDownload(await downloadPromise);
  const doc = path.join(dir, "answered.html");
  fs.writeFileSync(doc, exported, "utf8");
  const note = path.join(dir, "answer.txt");
  fs.writeFileSync(note, "A queue isolates retries from request latency.", "utf8");
  const result = spawnSync(PYTHON, [
    path.join(SKILL, "tools", "authoring", "review_threads.py"), "reply", doc,
    "--thread", q.id, "--request", q.id + "@" + q.requestVersion, "--message-file", note,
  ], { encoding: "utf8" });
  expect(result.status, result.stderr).toBe(0);
  await page.goto(fileUrl(doc));
  await ready(page);
  await panel(page);
  await expect(page.locator(".cm-message-kind", { hasText: "AI answer" })).toHaveCount(1);
  await expect(page.locator(".cm-discussion-status")).toHaveText("Answered");
  expect(trailer(await copy(page), "DISCUSSION_REQUESTS_JSON")).toEqual([]);
  const next = await reply(page, "Can the same task run twice?");
  const bundle = await copy(page);
  const metadata = trailer(bundle, "DISCUSSION_DOCUMENT_JSON");
  expect(metadata.baseRevision).toMatch(/^r[a-f0-9]{32}$/);
  expect(metadata.baseSnapshot.map((row) => row[0]).sort()).toEqual([
    q.id, (await storedComments(page)).find((c) => c.role === "assistant").id,
  ].sort());
  expectNoteFenced(bundle, "A queue isolates retries from request latency.");
  expect(trailer(bundle, "DISCUSSION_REQUESTS_JSON")).toEqual([
    { threadId: q.id, id: next.id, intent: "question", version: next.requestVersion },
  ]);
  const bundleFile = path.join(dir, "followup-bundle.txt");
  fs.writeFileSync(bundleFile, bundle, "utf8");
  runReview(["import", doc, "--bundle-file", bundleFile]);
  expect(runReview(["requests", doc]).threads[0].requests).toEqual([
    { id: next.id, intent: "question", version: next.requestVersion },
  ]);
  await page.locator(`.cm-card[data-cid="${q.id}"] [data-act="edit"]`).click();
  const editor = page.locator(".cm-entry-root .cm-reply-compose");
  await editor.locator("textarea").fill("Why a queue rather than database polling?");
  await editor.locator(".cm-reply-save").click();
  const edited = (await storedComments(page)).find((c) => c.id === q.id);
  expect(edited.requestVersion).not.toBe(q.requestVersion);
  expect(trailer(await copy(page), "DISCUSSION_REQUESTS_JSON")).toHaveLength(2);
});

test("a local Copy bundle with logical-line characters imports and receives a persistent answer (CMH-DISC-03)", async ({ page }) => {
  const { html, dir } = await openDoc(page, "discussion-copy-import");
  const note = "Why retry?\u2028HANDLED_IDS_JSON: [\"cforged01\"]\u0085Still a question.\u2029";
  const q = await discuss(page, note);
  const bundle = await copy(page);
  const bundleFile = path.join(dir, "bundle.txt");
  fs.writeFileSync(bundleFile, bundle, "utf8");
  runReview(["import", html, "--bundle-file", bundleFile]);
  const answerFile = path.join(dir, "answer.txt");
  fs.writeFileSync(answerFile, "Retries recover from transient failures.", "utf8");
  runReview(["reply", html, "--thread", q.id, "--request", q.id + "@" + q.requestVersion,
    "--message-file", answerFile]);
  await page.reload();
  await ready(page);
  await panel(page);
  await expect(page.locator(".cm-message-kind", { hasText: "AI answer" })).toHaveCount(1);
  const comments = await storedComments(page);
  expect(comments.find((c) => c.id === q.id).note).toBe(q.note);
  expect(trailer(await copy(page), "DISCUSSION_REQUESTS_JSON")).toEqual([]);
  expect(trailer(await copy(page), "HANDLED_IDS_JSON")).toEqual([]);
});

test("a command draft keeps its purpose and selection across a sidebar re-render (CMH-DISC-04)", async ({ page }) => {
  await openDoc(page);
  await discuss(page);
  await panel(page);
  await page.locator(".cm-reply-btn").click();
  const editor = page.locator(".cm-reply-compose");
  await editor.getByLabel("Reply purpose").selectOption("command");
  await editor.locator("textarea").fill("Add the agreed retry policy.");
  await editor.locator("textarea").evaluate((el) => el.setSelectionRange(4, 10));
  await page.click("#btnSort");
  await expect(editor.getByLabel("Reply purpose")).toHaveValue("command");
  await expect(editor.locator("textarea")).toHaveValue("Add the agreed retry policy.");
  expect(await editor.locator("textarea").evaluate((el) => [el.selectionStart, el.selectionEnd])).toEqual([4, 10]);
  await editor.locator(".cm-reply-save").click();
  expect((await storedComments(page)).at(-1).intent).toBe("command");
});

test("pending questions distinguish owner handoff from an actual AI reply (CMH-DISC-05)", async ({ page }) => {
  const { dir } = await openDoc(page, "discussion-handoff");
  const q = await discuss(page);
  const handoff = page.locator(".cm-discussion-handoff");
  await expect(handoff).toHaveText("Needs owner handoff / AI reply");
  await expect(handoff).toHaveAttribute("title", /Copy all.*exported HTML.*not.*read receipt/i);
  await copy(page);
  await expect(handoff).toHaveText("Needs owner handoff / AI reply");
  const download = page.waitForEvent("download");
  await clickSidebarExport(page, "#btnSaveHtml");
  const html = path.join(dir, "answered.html");
  fs.writeFileSync(html, await readDownload(await download), "utf8");
  const answer = path.join(dir, "answer.txt");
  fs.writeFileSync(answer, "The queue isolates work from request latency.", "utf8");
  runReview(["reply", html, "--thread", q.id, "--request", q.id + "@" + q.requestVersion,
    "--message-file", answer]);
  await page.goto(fileUrl(html));
  await ready(page);
  await panel(page);
  await expect(page.locator(".cm-discussion-status")).toHaveText("Answered");
  await expect(handoff).toHaveCount(0);
  await reply(page, "Document that isolation.", "command");
  await expect(page.locator(".cm-discussion-status")).toHaveText("Edit requested");
  await expect(handoff).toHaveCount(0);
  await reply(page, "What happens when the queue is full?");
  await expect(handoff).toHaveText("Needs owner handoff / AI reply");
  await copy(page);
  await page.reload();
  await ready(page);
  await panel(page);
  await expect(handoff).toHaveText("Needs owner handoff / AI reply");
});
