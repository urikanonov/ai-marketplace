import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  INLINE, fileUrl, ready, installClipboardCapture, addTextComment, lastCopied, storedComments,
  clickSidebarExport, readDownload,
} from "./helpers.js";

const INLINE_HTML = fs.readFileSync(INLINE, "utf8");
const CONTENT_END = "<!-- END: commentable-html - CONTENT -->";
const DEMO_ROOT_RE = /<main id="commentRoot"(?=[^>]*data-comment-key="commentable-html-demo")[^>]*>/;

function withContent(snippet) {
  return INLINE_HTML.replace(CONTENT_END, snippet + "\n" + CONTENT_END);
}

function withEmbeddedComments(comments) {
  const json = JSON.stringify(comments).replace(/</g, "\\u003c");
  return INLINE_HTML.replace(
    /<script type="application\/json" id="embeddedComments">[\s\S]*?<\/script>/,
    '<script type="application/json" id="embeddedComments">\n' + json + "\n</script>");
}

async function openFromRoute(page, url, html) {
  await installClipboardCapture(page);
  await page.route(url, (route) => route.fulfill({ status: 200, contentType: "text/html", body: html }));
  await page.goto(url);
  await ready(page);
}

test("body fallback anchors comments when #commentRoot is absent (CMH-CORE-15)", async ({ page }) => {
  const url = "http://localhost/body-fallback.html";
  const html = INLINE_HTML.replace(DEMO_ROOT_RE, '<main id="contentWithoutCommentRoot">');
  await openFromRoute(page, url, html);

  await expect(page.locator("#commentRoot")).toHaveCount(0);
  await addTextComment(page, "main p", "body fallback note", 0);

  const stored = await storedComments(page);
  expect(stored).toHaveLength(1);
  expect(await page.locator("mark.cm-hl").evaluateAll((marks) => new Set(marks.map((m) => m.dataset.cid)).size)).toBe(1);

  await page.locator("#btnCopyAll").click();
  const bundle = await lastCopied(page);
  expect(bundle).toContain("# Commentable HTML - Demo review (1 comment)");
  expect(bundle).toContain("Source: body-fallback.html");
  expect(bundle).toContain("body fallback note");
});

test("body fallback Portable export strips source directories (CMH-SEC-03)", async ({ page }) => {
  const url = "http://localhost/body-fallback-export.html";
  const html = INLINE_HTML
    .replace(DEMO_ROOT_RE, '<main id="contentWithoutCommentRoot">')
    .replace("<body", String.raw`<body data-doc-source="C:\Users\alice\Internal Project\report.html"`);
  await openFromRoute(page, url, html);
  await addTextComment(page, "main p", "export body fallback", 0);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnSaveHtml"),
  ]);
  const exported = await readDownload(download);
  const body = exported.match(/<body\b[^>]*>/i);
  expect(body).toBeTruthy();
  expect(body[0]).toContain('data-doc-source="report.html"');
  expect(exported).not.toContain("alice");
  expect(exported).not.toContain("Internal Project");
});

test("per-block copy failures show Copy failed without opening prompt (CMH-COPY-06)", async ({ page }) => {
  await page.addInitScript(() => {
    window.__promptCalls = [];
    window.__copyAttempts = { clipboard: 0, exec: 0 };
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async () => { window.__copyAttempts.clipboard += 1; throw new Error("blocked"); } },
    });
    document.execCommand = () => { window.__copyAttempts.exec += 1; return false; };
    window.prompt = (...args) => { window.__promptCalls.push(args); return null; };
  });
  await page.goto(fileUrl(INLINE));
  await ready(page);

  await page.locator('#commentRoot .cmh-code-wrap:has(code.language-python) .cm-code-copy').first().click();
  await expect(page.locator("#toast")).toContainText("Copy failed");
  expect(await page.evaluate(() => window.__promptCalls.length)).toBe(0);

  await page.locator(".cmh-kql-cluster").first().click();
  await expect(page.locator("#toast")).toContainText("Copy failed");
  expect(await page.evaluate(() => window.__promptCalls.length)).toBe(0);
  expect(await page.evaluate(() => window.__copyAttempts)).toEqual({ clipboard: 2, exec: 2 });
});

test("content pre blocks wrap while diff and mermaid pre blocks keep their own whitespace (CMH-CONTENT-13)", async ({ page }) => {
  await page.goto(fileUrl(INLINE));
  await ready(page);
  const styles = await page.evaluate(() => {
    const root = document.getElementById("commentRoot");
    root.insertAdjacentHTML("beforeend", [
      '<pre id="probePlain">alpha beta gamma delta epsilon</pre>',
      '<pre id="probeCode"><code>alpha beta gamma delta epsilon</code></pre>',
      '<pre id="probeDiff" class="cmh-diff">@@ -1 +1 @@\n-old\n+new</pre>',
      '<pre id="probeRaw" class="cmh-diff-raw">raw diff text</pre>',
      '<pre id="probeMermaid" class="mermaid cm-skip">graph TD; A-->B;</pre>',
    ].join(""));
    const styleFor = (id) => {
      const cs = getComputedStyle(document.getElementById(id));
      return { whiteSpace: cs.whiteSpace, overflowWrap: cs.overflowWrap };
    };
    return {
      plain: styleFor("probePlain"),
      code: styleFor("probeCode"),
      diff: styleFor("probeDiff"),
      raw: styleFor("probeRaw"),
      mermaid: styleFor("probeMermaid"),
    };
  });

  expect(styles.plain).toEqual({ whiteSpace: "pre-wrap", overflowWrap: "anywhere" });
  expect(styles.code).toEqual({ whiteSpace: "pre-wrap", overflowWrap: "anywhere" });
  expect(styles.diff.whiteSpace).not.toBe("pre-wrap");
  expect(styles.raw.whiteSpace).not.toBe("pre-wrap");
  expect(styles.mermaid.whiteSpace).not.toBe("pre-wrap");
});

test("browser heading ids fall back to ASCII section slugs for non-Latin headings (CMH-TOC-06)", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  const snippet = `
    <section><h2>\u6E2C\u8A66</h2><p>First non-Latin heading.</p></section>
    <section><h2>\u8CC7\u6599</h2><p>Second non-Latin heading.</p></section>
  `;
  await openFromRoute(page, "http://localhost/non-latin-headings.html", withContent(snippet));

  const ids = await page.locator("#commentRoot section").evaluateAll((sections) =>
    sections.slice(-2).map((s) => s.querySelector("h2").id));
  expect(ids).toEqual(["section", "section-2"]);
  await expect(page.locator("#section")).toHaveClass(/cm-anchored/);
  await page.locator("#section").click();
  await expect.poll(() => page.evaluate(() => location.hash)).toBe("#section");
});

test("persistence sidecar keys are written under the document key (CMH-PERSIST-01)", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto(fileUrl(INLINE));
  await ready(page);
  await addTextComment(page, "#commentRoot section p", "sidecar note", 0);
  const [comment] = await storedComments(page);

  await openFromRoute(page, "http://localhost/embedded-sidecar.html", withEmbeddedComments([comment]));
  const key = await page.locator("#commentRoot").evaluate((root) => root.dataset.commentKey);
  await expect(page.locator(".cm-card")).toHaveCount(1);
  await page.locator("#btnSortAsc").click();
  await page.locator(".cmh-diff-toggle").first().click();
  await page.locator(".cmh-diff-hltoggle").first().click();
  await page.locator("#commentRoot table.cmh-sortable thead th", { hasText: "Requests" }).locator(".cmh-sort-ctrl").click();
  await page.locator(".cm-card [data-act='del']").first().click();
  await expect(page.locator(".cm-card")).toHaveCount(0);

  const state = await page.evaluate((k) => {
    const zraw = localStorage.getItem(k + "::z");
    const dec = zraw ? window.__cmhStorageCodec.decode(zraw) : { json: "[]" };
    return {
      commentCount: JSON.parse(dec.json || "[]").length,
      legacy: localStorage.getItem(k),
      deleted: JSON.parse(localStorage.getItem(k + "::deleted") || "[]"),
      commentSort: localStorage.getItem(k + "::commentSort"),
      diffLayout: localStorage.getItem(k + "::diffLayout"),
      diffSyntax: localStorage.getItem(k + "::diffSyntax"),
      tableSort: JSON.parse(localStorage.getItem(k + "::tableSort") || "{}"),
    };
  }, key);
  expect(state.commentCount).toBe(0);   // the modern ::z store holds the (now empty) comment array
  expect(state.legacy).toBeNull();       // the legacy base key was reclaimed
  expect(state.deleted).toContain(comment.id);
  expect(state.commentSort).toBe("time-asc");
  expect(state.diffLayout).toBe("inline");
  expect(state.diffSyntax).toBe("off");
  expect(Object.values(state.tableSort)).toContainEqual({ col: 1, dir: "asc" });
});

test("invalid localStorage JSON degrades to defaults without breaking startup (CMH-PERSIST-01)", async ({ page }) => {
  const pageErrors = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));
  await page.addInitScript(() => {
    const key = "commentable-html-demo";
    localStorage.setItem(key, "{bad");
    localStorage.setItem(key + "::deleted", "{bad");
    localStorage.setItem(key + "::tableSort", "{bad");
    localStorage.setItem(key + "::commentSort", "not-a-sort-mode");
    localStorage.setItem(key + "::diffLayout", "bad-layout");
    localStorage.setItem(key + "::diffSyntax", "off");
  });
  await page.goto(fileUrl(INLINE));
  await ready(page);

  await expect(page.locator(".cm-card")).toHaveCount(0);
  await expect(page.locator(".cmh-diff-view").first()).toHaveClass(/cmh-diff-split/);
  await expect(page.locator("#btnSortAsc")).toHaveAttribute("aria-pressed", "false");
  expect(pageErrors).toEqual([]);
});

test("primary comment save failure stays usable but warns that persistence failed (CMH-PERSIST-01)", async ({ page }) => {
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (String(key).startsWith("commentable-html-demo")) throw new Error("blocked storage");
      return original.call(this, key, value);
    };
  });
  await page.goto(fileUrl(INLINE));
  await ready(page);

  await addTextComment(page, "#commentRoot section p", "storage failure note", 0);
  await expect(page.locator(".cm-card")).toHaveCount(1);
  await expect(page.locator("#toast")).toContainText("Comment NOT saved to this browser");

  await page.reload();
  await ready(page);
  await expect(page.locator(".cm-card")).toHaveCount(0);
});
