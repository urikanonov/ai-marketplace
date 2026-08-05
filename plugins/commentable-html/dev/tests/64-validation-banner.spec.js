import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { fileUrl, ready, stageContent, installClipboardCapture, openToolbarMenu, PYTHON, SKILL, KITCHEN_SINK } from "./helpers.js";

// CMH-STAMP-03: the runtime shows a small dismissible amber fallback banner when a document carries a
// commentable-html-created stamp but no current commentable-html-validated stamp - a produced but
// never-strict-validated document. A validated document (and one with no created stamp) shows nothing.

const CONTENT = "<h1>Doc</h1><p>Body text for the document.</p>";

function injectMetas(htmlPath, metas) {
  let html = fs.readFileSync(htmlPath, "utf8");
  const tags = Object.entries(metas)
    .map(([name, content]) => '<meta name="' + name + '" content="' + content + '" />')
    .join("\n");
  html = html.replace(/<head[^>]*>/i, (m) => m + "\n" + tags);
  fs.writeFileSync(htmlPath, html);
}

async function open(page, metas, key) {
  const staged = stageContent(CONTENT, { key });
  injectMetas(staged.html, metas);
  await installClipboardCapture(page);
  await page.goto(fileUrl(staged.html));
  await ready(page);
  return staged;
}

test.describe("unvalidated-document fallback banner (CMH-STAMP-03)", () => {
  test("an unvalidated document shows the fallback banner", async ({ page }) => {
    await open(page, { "commentable-html-created": "2026-07-15T10:00:00Z" }, "cmh-banner-1");
    const banner = page.locator(".cmh-unvalidated-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("not validated");
  });

  test("a validated document shows no banner", async ({ page }) => {
    await open(page, {
      "commentable-html-created": "2026-07-15T10:00:00Z",
      "commentable-html-validated": "2026-07-15T10:05:00Z",
    }, "cmh-banner-2");
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
  });

  test("a validation older than creation still shows the banner", async ({ page }) => {
    await open(page, {
      "commentable-html-created": "2026-07-15T10:05:00Z",
      "commentable-html-validated": "2026-07-15T10:00:00Z",
    }, "cmh-banner-3");
    await expect(page.locator(".cmh-unvalidated-banner")).toBeVisible();
  });

  test("a document with no created stamp shows no banner", async ({ page }) => {
    await open(page, {}, "cmh-banner-4");
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
  });

  test("the banner is dismissible", async ({ page }) => {
    await open(page, { "commentable-html-created": "2026-07-15T10:00:00Z" }, "cmh-banner-5");
    const banner = page.locator(".cmh-unvalidated-banner");
    await expect(banner).toBeVisible();
    await banner.locator(".cmh-unvalidated-dismiss").click();
    await expect(banner).toHaveCount(0);
  });

  test("the banner does not leak into a Plain export", async ({ page }) => {
    await open(page, { "commentable-html-created": "2026-07-15T10:00:00Z" }, "cmh-banner-6");
    await expect(page.locator(".cmh-unvalidated-banner")).toBeVisible();
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnSavePlainTop").click(),
    ]);
    const saved = fs.readFileSync(await download.path(), "utf8");
    // The runtime-injected banner element (and its message) must not bake into the plain copy; the
    // inert layer CSS rule that styles it is harmlessly retained like every other stylesheet.
    expect(saved).not.toContain("This document was not validated");
    expect(saved).not.toContain('class="cm-skip cmh-unvalidated-banner"');
  });
});

// CMH-STAMP-05: the validated stamp is CONTENT-BOUND. validate.py/finalize.py also write a
// commentable-html-validated-hash (the whole content-root text hashed with the shared section-hash
// contract), and the runtime shows the banner when the live content hash no longer matches it - a
// document that was strict-validated and THEN manually edited.
test.describe("content-bound validation stamp (CMH-STAMP-05)", () => {
  function injectMetasInto(htmlPath, metas) {
    let html = fs.readFileSync(htmlPath, "utf8");
    const tags = Object.entries(metas)
      .map(([name, content]) => '<meta name="' + name + '" content="' + content + '" />')
      .join("\n");
    html = html.replace(/<head[^>]*>/i, (m) => m + "\n" + tags);
    fs.writeFileSync(htmlPath, html);
  }

  function editContent(htmlPath, extraHtml) {
    const END = "<!-- END: commentable-html - CONTENT -->";
    let html = fs.readFileSync(htmlPath, "utf8");
    html = html.replace(END, extraHtml + "\n" + END);
    fs.writeFileSync(htmlPath, html);
  }

  const DOC = "<h1>Content bound doc</h1><p>Original body text for the document.</p>";

  test("the runtime exposes a stable whole-document content hash", async ({ page }) => {
    const staged = stageContent(DOC, { key: "cmh-dochash-1" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const first = await page.evaluate(() => window.__cmhReview && window.__cmhReview.docHash());
    expect(typeof first).toBe("string");
    expect(first).toMatch(/^[0-9a-z]+$/);
    // Recomputing on the loaded document is stable (runtime chrome/highlighting do not move it).
    const second = await page.evaluate(() => window.__cmhReview.docHash());
    expect(second).toBe(first);
  });

  test("a validated document whose content hash matches shows no banner", async ({ page }) => {
    const staged = stageContent(DOC, { key: "cmh-cbind-match" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const liveHash = await page.evaluate(() => window.__cmhReview.docHash());
    injectMetasInto(staged.html, {
      "commentable-html-created": "2026-07-15T10:00:00Z",
      "commentable-html-validated": "2026-07-15T10:05:00Z",
      "commentable-html-validated-hash": liveHash,
    });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
  });

  test("a validated document whose content hash no longer matches shows the banner", async ({ page }) => {
    const staged = stageContent(DOC, { key: "cmh-cbind-mismatch" });
    // A validated stamp that post-dates creation (so the timestamp path is clean) but a stale hash:
    // only the content-hash mismatch can raise the banner here, proving content-binding.
    injectMetasInto(staged.html, {
      "commentable-html-created": "2026-07-15T10:00:00Z",
      "commentable-html-validated": "2026-07-15T10:05:00Z",
      "commentable-html-validated-hash": "staleHash0",
    });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(page.locator(".cmh-unvalidated-banner")).toBeVisible();
  });

  test("validate.py content-binds the stamp end to end (Python/JS hash parity, edit re-shows, re-validate clears)", async ({ page }) => {
    // A genuinely strict-clean document (new_document builds one; a bare content fragment can carry
    // validator warnings that would legitimately block the stamp). new_document stamps created; a
    // subsequent validate.py stamps validated + validated-hash.
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_cbind_"));
    const docPath = path.join(dir, "doc.html");
    execFileSync(PYTHON, ["tools/authoring/new_document.py", "--content", "-", "--key",
      "cmh-cbind-e2e", "--label", "Content bound", "--kind", "report", "--source", "doc.html",
      "--shareable", "--out", docPath], { cwd: SKILL, input: DOC });
    execFileSync(PYTHON, ["tools/validate/validate.py", docPath], { cwd: SKILL });
    // The real <meta> stamp (matched as a tag, not the meta NAME which also appears in the inlined
    // runtime JS that reads it).
    expect(fs.readFileSync(docPath, "utf8"))
      .toMatch(/<meta name="commentable-html-validated-hash" content="[0-9a-z]+"/);
    // 1) The Python-stamped hash matches the live runtime hash, so no banner (real parity check).
    await page.goto(fileUrl(docPath));
    await ready(page);
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
    // 2) A hand edit after validation re-shows the banner (the stamped hash no longer matches),
    //    even though the validated timestamp still post-dates creation.
    editContent(docPath, "<p>An extra sentence added by hand after validation.</p>");
    await page.goto(fileUrl(docPath));
    await ready(page);
    await expect(page.locator(".cmh-unvalidated-banner")).toBeVisible();
    // 3) Re-running validate.py re-stamps the hash for the new content, clearing the banner again.
    execFileSync(PYTHON, ["tools/validate/validate.py", docPath], { cwd: SKILL });
    await page.goto(fileUrl(docPath));
    await ready(page);
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
  });

  test("the Python and runtime document hashes agree on rich content (kitchen-sink parity)", async ({ page }) => {
    // Pin the core parity claim (Python document_content_hash == runtime docHash) over the
    // kitchen-sink fixture, which exercises baked-highlighted code, tables, rendered diff/KQL,
    // chart canvas, editable notes, and a <noscript> - the content types where a file-parse vs
    // DOM-textContent divergence would false-positive the banner on a valid document.
    await page.goto(fileUrl(KITCHEN_SINK));
    await ready(page);
    const jsHash = await page.evaluate(() => window.__cmhReview.docHash());
    const pyHash = execFileSync(PYTHON, ["-c",
      "import sys,section_hash;print(section_hash.document_content_hash(open(sys.argv[1],encoding='utf-8').read()),end='')",
      KITCHEN_SINK], { cwd: path.join(SKILL, "tools", "authoring") }).toString();
    expect(pyHash).toBe(jsHash);
    expect(jsHash).toMatch(/^[0-9a-z]+$/);
  });

  test("shared parser boundaries preserve browser section-hash parity (CMH-VAL-21)", async ({ page }) => {
    const cases = [
      {
        key: "cmh-boundary-implicit",
        content: '<p class="cm-skip">Hidden<h2 id="shown">Shown</h2><p>Body</p>',
      },
      {
        key: "cmh-boundary-self-close",
        content: '<h2 id="shown"/>Shown</h2><p>Body</p>',
      },
      {
        key: "cmh-boundary-list-item",
        content: '<ul><li class="cm-skip">Hidden<li><h2 id="shown">Shown</h2><p>Body</p></ul>',
      },
      {
        key: "cmh-boundary-rcdata",
        content: '<textarea><h2 id="ghost">Ghost</h2></textarea><h2 id="shown">Shown</h2>',
      },
      {
        key: "cmh-boundary-rcdata-reference",
        content: '<h2 id="shown">Shown</h2><textarea>Fish &amp; Chips</textarea>',
      },
      {
        key: "cmh-boundary-leading-lf",
        content: '<h2 id="shown">Shown</h2><pre>\nBody</pre>',
      },
    ];
    for (const entry of cases) {
      const staged = stageContent(entry.content, { key: entry.key });
      await page.goto(fileUrl(staged.html));
      await ready(page);
      const jsSections = await page.evaluate(() => Object.fromEntries(
        Array.from(document.querySelectorAll("#commentRoot h1, #commentRoot h2, #commentRoot h3, #commentRoot h4, #commentRoot h5, #commentRoot h6"))
          .filter((heading) => heading.id && !heading.closest(".cm-skip"))
          .map((heading) => [heading.id, window.__cmhReview.sectionHashOf(heading.id)]),
      ));
      const pySections = JSON.parse(execFileSync(PYTHON, ["-c", [
        "import json,sys,section_hash",
        "html=open(sys.argv[1],encoding='utf-8').read()",
        "print(json.dumps({s['id']:s['hash'] for s in section_hash.extract_sections(html) if s['id']}))",
      ].join(";"), staged.html], {
        cwd: path.join(SKILL, "tools", "authoring"),
      }).toString());
      expect(pySections).toEqual(jsSections);
    }
  });

  test("a persisted table sort does not falsely invalidate the stamp (canonical hash)", async ({ page }) => {
    // A reader sorting a table is a runtime-only DOM reorder the source-order stamp never saw; the
    // canonical (unsorted) docHash must still match so the banner stays down after reload.
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_sort_"));
    const docPath = path.join(dir, "doc.html");
    // Rows are separated by NEWLINES, like a real authored table: the tbody then holds whitespace
    // text nodes between them, which is what makes a naive reorder drift the hash (CMH-CONTENT-20).
    const tableDoc = [
      "<h1>Sortable report</h1>",
      "<p>Intro prose.</p>",
      "<table>",
      "  <thead>",
      "    <tr><th>Name</th><th>Count</th></tr>",
      "  </thead>",
      "  <tbody>",
      "    <tr><td>Bravo</td><td>2</td></tr>",
      "    <tr><td>Alpha</td><td>1</td></tr>",
      "    <tr><td>Charlie</td><td>3</td></tr>",
      "  </tbody>",
      "</table>",
    ].join("\n");
    execFileSync(PYTHON, ["tools/authoring/new_document.py", "--content", "-", "--key",
      "cmh-sort-e2e", "--label", "Sortable", "--kind", "report", "--source", "doc.html",
      "--shareable", "--out", docPath], { cwd: SKILL, input: tableDoc });
    execFileSync(PYTHON, ["tools/validate/validate.py", docPath], { cwd: SKILL });
    await page.goto(fileUrl(docPath));
    await ready(page);
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
    // Sort the first column (physically reorders <tr> rows and persists to localStorage).
    const sortBtn = page.locator("table.cmh-sortable th .cmh-sort-ctrl").first();
    await expect(sortBtn).toHaveCount(1);
    await sortBtn.click();
    // Reload from the same file URL: the persisted sort re-applies before the banner hashes.
    await page.goto(fileUrl(docPath));
    await ready(page);
    await expect(page.locator("table.cmh-sortable")).toHaveCount(1);
    // Prove the sort actually persisted and re-applied (else this test could pass on a no-op): the
    // Name column is now ascending (Alpha, Bravo, Charlie) and the control reflects the asc state.
    await expect(page.locator("table.cmh-sortable tbody tr td:first-child"))
      .toHaveText(["Alpha", "Bravo", "Charlie"]);
    await expect(page.locator("table.cmh-sortable th .cmh-sort-ctrl").first())
      .toHaveAttribute("aria-pressed", "true");
    // Despite the persisted (re-applied) sort, the canonical hash matches the stamp: no banner.
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
  });

  test("a persisted sort of a whitespace-formatted table does not falsely invalidate the stamp", async ({ page }) => {
    // Regression (#952): a real authored table has NEWLINES between its <tr> rows, so the tbody
    // carries whitespace text nodes between them. A sort that appended every row to the end left
    // that whitespace stranded ahead of the rows, so the rows became textually adjacent - a change
    // the canonical (unsorted) hash could not undo, because unsorting restores row ORDER only.
    // The document hash therefore drifted the moment a reader sorted a table, and since the sort is
    // persisted per browser profile the banner appeared on ONE machine and not another for the very
    // same file. The rows must be permuted through their existing slots so sorting is text-neutral.
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_sortws_"));
    const docPath = path.join(dir, "doc.html");
    const tableDoc = [
      "<h1>Sortable report</h1>",
      "<p>Intro prose.</p>",
      "<table>",
      "  <thead>",
      "    <tr><th>Name</th><th>Count</th></tr>",
      "  </thead>",
      "  <tbody>",
      "    <tr><td>Bravo</td><td>2</td></tr>",
      "    <tr><td>Alpha</td><td>1</td></tr>",
      "    <tr><td>Charlie</td><td>3</td></tr>",
      "  </tbody>",
      "</table>",
    ].join("\n");
    execFileSync(PYTHON, ["tools/authoring/new_document.py", "--content", "-", "--key",
      "cmh-sortws-e2e", "--label", "Sortable ws", "--kind", "report", "--source", "doc.html",
      "--portable", "--out", docPath], { cwd: SKILL, input: tableDoc });
    execFileSync(PYTHON, ["tools/validate/validate.py", docPath], { cwd: SKILL });
    await page.goto(fileUrl(docPath));
    await ready(page);
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
    const before = await page.evaluate(() => window.__cmhReview.docHash());
    // Sorting live must not move the document hash (the canonical hash unsorts before hashing).
    await page.locator("table.cmh-sortable th .cmh-sort-ctrl").first().click();
    await expect(page.locator("table.cmh-sortable tbody tr td:first-child"))
      .toHaveText(["Alpha", "Bravo", "Charlie"]);
    expect(await page.evaluate(() => window.__cmhReview.docHash())).toBe(before);
    // ...and neither must the persisted sort re-applied on the next load: no banner, same hash.
    await page.goto(fileUrl(docPath));
    await ready(page);
    await expect(page.locator("table.cmh-sortable tbody tr td:first-child"))
      .toHaveText(["Alpha", "Bravo", "Charlie"]);
    expect(await page.evaluate(() => window.__cmhReview.docHash())).toBe(before);
    await expect(page.locator(".cmh-unvalidated-banner")).toHaveCount(0);
  });

  test("authored data-cmh-row attributes cannot redefine the canonical order (JS/Python parity)", async ({ page }) => {
    // The runtime OWNS the row index: it stamps every sortable row with its position in the FILE at
    // load, before any persisted sort is applied. A document that ships its own data-cmh-row values
    // (hand-authored, or left over from an older build) must not be able to define a different
    // "canonical" order, or the runtime would hash rows in that order while the Python hasher reads
    // the source order - reviving the false banner from the other side (#952).
    const staged = stageContent([
      "<h1>Stamped rows</h1>",
      "<table>",
      "  <thead>",
      "    <tr><th>Name</th><th>Count</th></tr>",
      "  </thead>",
      "  <tbody>",
      "    <tr data-cmh-row=\"2\"><td>Bravo</td><td>2</td></tr>",
      "    <tr data-cmh-row=\"1\"><td>Alpha</td><td>1</td></tr>",
      "    <tr data-cmh-row=\"0\"><td>Charlie</td><td>3</td></tr>",
      "  </tbody>",
      "</table>",
    ].join("\n"), { key: "cmh-authored-rowidx" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // Persist a sort, so the canonical read is engaged on the next load.
    await page.locator("table.cmh-sortable th .cmh-sort-ctrl").first().click();
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const jsHash = await page.evaluate(() => window.__cmhReview.docHash());
    const pyHash = execFileSync(PYTHON, ["-c",
      "import sys,section_hash;print(section_hash.document_content_hash(open(sys.argv[1],encoding='utf-8').read()),end='')",
      staged.html], { cwd: path.join(SKILL, "tools", "authoring") }).toString();
    expect(jsHash).toBe(pyHash);
  });

  test("in-root noscript is excluded from the hash on both sides (JS/Python parity)", async ({ page }) => {
    // The kitchen-sink noscript sits OUTSIDE #commentRoot, so this pins the in-root case: a
    // <noscript> whose markup the browser exposes as literal text must be excluded on BOTH sides,
    // so the runtime docHash equals the Python document_content_hash for the same file.
    const staged = stageContent(
      "<h1>Doc</h1><p>Body text here.</p><noscript><b>Enable JavaScript to review.</b></noscript>",
      { key: "cmh-noscript-parity" });
    await page.goto(fileUrl(staged.html));
    await ready(page);
    const jsHash = await page.evaluate(() => window.__cmhReview.docHash());
    const pyHash = execFileSync(PYTHON, ["-c",
      "import sys,section_hash;print(section_hash.document_content_hash(open(sys.argv[1],encoding='utf-8').read()),end='')",
      staged.html], { cwd: path.join(SKILL, "tools", "authoring") }).toString();
    expect(pyHash).toBe(jsHash);
  });
});
