import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  ready, openToolbarMenu, startStaticServer, stageInline, stageNonPortable,
} from "./helpers.js";

// CMH-TOOL-08: the runtime export path must refuse to write a file when a
// commentable-html layer region has duplicated markers. _assertSingleLayerRegions
// runs inside _buildPlainHtml (Export Plain, every mode) and inside
// _inlineNonPortableAssets (Export Offline for a nonportable document). A duplicated
// BEGIN marker (F28) or a duplicated END marker (F37) in the EMBEDDED COMMENTS region
// must abort the export with a toast and download nothing. The base HTML is fetched
// over http here so the guard sees the raw on-disk duplicates (the file:// snapshot
// path collapses the pre-<html> comment and was never the vulnerable case).

const EMBED_END = "<!-- END: commentable-html - EMBEDDED COMMENTS -->";

// Duplicate the EMBEDDED COMMENTS BEGIN marker (two BEGIN, one END) -> F28.
function duplicateBegin(html) {
  return html.replace(EMBED_END, "<!-- BEGIN: commentable-html - EMBEDDED COMMENTS -->\n" + EMBED_END);
}

// Duplicate the EMBEDDED COMMENTS END marker (one BEGIN, two END) -> F37.
function duplicateEnd(html) {
  return html.replace(EMBED_END, EMBED_END + "\n" + EMBED_END);
}

async function expectExportAborts(page, server, urlPath, buttonId) {
  let downloadFired = false;
  page.on("download", () => { downloadFired = true; });
  await page.goto(server.url + urlPath);
  await ready(page);
  await openToolbarMenu(page);
  await page.locator("#" + buttonId).dispatchEvent("click");
  await page.waitForFunction(() => {
    const t = document.getElementById("toast");
    return !!t && t.classList.contains("show") && /Export aborted/.test(t.textContent || "");
  }, null, { timeout: 8000 });
  const toast = await page.evaluate(() => document.getElementById("toast").textContent || "");
  expect(toast).toContain("Export aborted");
  expect(toast).toContain("EMBEDDED COMMENTS");
  // Nothing must have downloaded; give a stray download a brief chance to appear.
  await page.waitForTimeout(300);
  expect(downloadFired).toBe(false);
}

test.describe("runtime region guard aborts export on duplicated layer markers (CMH-TOOL-08)", () => {
  test("Export Plain aborts on a duplicated EMBEDDED COMMENTS BEGIN marker (F28)", async ({ page }) => {
    const staged = stageInline({ mutate: duplicateBegin });
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/doc.html", "btnSavePlain");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Export Plain aborts on a duplicated EMBEDDED COMMENTS END marker (F37)", async ({ page }) => {
    const staged = stageInline({ mutate: duplicateEnd });
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/doc.html", "btnSavePlain");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Export Offline aborts on a duplicated EMBEDDED COMMENTS BEGIN marker in a nonportable doc (F28)", async ({ page }) => {
    const staged = stageNonPortable({ companions: true, mutate: duplicateBegin });
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/NONPORTABLE.html", "btnExportOffline");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Export Offline aborts on a duplicated EMBEDDED COMMENTS END marker in a nonportable doc (F37)", async ({ page }) => {
    const staged = stageNonPortable({ companions: true, mutate: duplicateEnd });
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/NONPORTABLE.html", "btnExportOffline");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });
});
