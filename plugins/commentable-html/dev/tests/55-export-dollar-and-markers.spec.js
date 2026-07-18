import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  openInline, addTextComment, readDownload, stageInline, startStaticServer,
  ready, openToolbarMenu,
  clickSidebarExport,
} from "./helpers.js";

// F2: the Export as Portable saved-HTML builder must NOT let a comment note that
// contains a `$`-replacement pattern ($&, $1, $`, $', $$) be reinterpreted by
// String.replace when the embedded-comments region is spliced in. Before the fix
// the replacement string expanded those patterns and corrupted the stored JSON,
// breaking reload. The builder now uses a function replacer.
test("Export as Portable preserves a comment note containing $-replacement patterns (F2)", async ({ page }) => {
  await openInline(page);
  const note = "regex $& and $1 and $` and $' and $$ literally";
  await addTextComment(page, "#commentRoot section p", note);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    clickSidebarExport(page, "#btnSaveHtml"),
  ]);
  const html = await readDownload(download);
  const m = html.match(/id="embeddedComments">([\s\S]*?)<\/script>/);
  expect(m).toBeTruthy();
  // The stored note round-trips EXACTLY - no $-pattern was expanded into it.
  expect(JSON.parse(m[1].trim())[0].note).toBe(note);
});

// F3: Export as Plain must strip a comment-data region whose banner uses the
// compact single-line marker form (no `===` decoration) that the validator's
// `=*` grammar also accepts. Before the fix the strip regex required `=+`, so a
// compact-markered document could not be exported to plain (the safety net threw).
function compactEmbeddedBegin(html) {
  return html.replace(
    /<!--\s*=+\s*BEGIN: commentable-html - EMBEDDED COMMENTS[\s\S]*?-->/,
    "<!-- BEGIN: commentable-html - EMBEDDED COMMENTS -->",
  );
}

test("Export as Plain strips a compact-markered EMBEDDED COMMENTS region (F3)", async ({ page }) => {
  const staged = stageInline({ mutate: compactEmbeddedBegin });
  const server = await startStaticServer(staged.dir);
  try {
    await page.goto(server.url + "/doc.html");
    await ready(page);
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSavePlainTop"),
    ]);
    const html = await readDownload(download);
    // The comment-data scripts were removed cleanly (no leak, no aborted export).
    expect(html).not.toContain('id="embeddedComments"');
    expect(html).not.toContain('id="handledCommentIds"');
    expect(html).not.toContain("__commentableHtmlReady");
    // Host content still survives the plain export.
    expect(html).toMatch(/#commentRoot\s+table\s*\{/);
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});
