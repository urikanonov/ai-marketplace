import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  ready, openToolbarMenu, startStaticServer, stageInline, stageNonShareable,
} from "./helpers.js";

// CMH-TOOL-08: the runtime export path must refuse to write a file when a
// commentable-html layer region has duplicated markers. _assertSingleLayerRegions
// runs inside _buildPlainHtml (Export Plain, every mode) and inside
// _inlineNonShareableAssets (Export Offline for a nonshareable document). A duplicated
// BEGIN marker (F28) or a duplicated END marker (F37) in the EMBEDDED COMMENTS region
// must abort the export with a toast and download nothing. The base HTML is fetched
// over http here so the guard sees the raw on-disk duplicates (the file:// snapshot
// path collapses the pre-<html> comment and was never the vulnerable case).

const EMBED_END = "<!-- END: commentable-html - EMBEDDED COMMENTS -->";
const CONTENT_END = "<!-- END: commentable-html - CONTENT -->";

// Duplicate the EMBEDDED COMMENTS BEGIN marker (two BEGIN, one END) -> F28.
function duplicateBegin(html) {
  return html.replace(EMBED_END, "<!-- BEGIN: commentable-html - EMBEDDED COMMENTS -->\n" + EMBED_END);
}

// Duplicate the EMBEDDED COMMENTS END marker (one BEGIN, two END) -> F37.
function duplicateEnd(html) {
  return html.replace(EMBED_END, EMBED_END + "\n" + EMBED_END);
}

// The damaged-region case: the layer's OWN END marker is botched by a hand edit, and an authored
// <script> in the CONTENT region quotes the marker on a line of its own. A text-only scan counts
// exactly one BEGIN and one END and calls the region well formed, so the Plain strip anchors on the
// authored quotation and deletes from the real BEGIN through the author's content.
function damagedEndQuotedInScriptText(html) {
  const out = html.replace(EMBED_END, "<!-- END: commentable-html - EMBEDDED COMMENTS (damaged) -->");
  if (out === html) throw new Error("fixture premise: no EMBEDDED COMMENTS END marker to damage");
  const quoted = '<script type="text/plain" id="cmhAuthoredMarkerSample">\n'
    + EMBED_END + "\n</" + "script>\n";
  if (!out.includes(CONTENT_END)) throw new Error("fixture premise: no CONTENT END marker");
  return out.replace(CONTENT_END, quoted + CONTENT_END);
}

// The identity case, not just the count case: the layer's REAL end marker closed with the legacy
// `--!>` (a comment-end-bang close a browser honours and the text locator rejects), beside an
// authored quotation the locator DOES see. Both views then report exactly one END marker - they are
// simply not the SAME marker - and the strip, which requires `-->`, anchors on the quotation.
function legacyCloseWithQuotedDecoy(html) {
  const out = html.replace(EMBED_END, "<!-- END: commentable-html - EMBEDDED COMMENTS --!>");
  if (out === html) throw new Error("fixture premise: no EMBEDDED COMMENTS END marker to rewrite");
  const quoted = '<script type="text/plain" id="cmhAuthoredMarkerSample">\n'
    + EMBED_END + "\n</" + "script>\n";
  if (!out.includes(CONTENT_END)) throw new Error("fixture premise: no CONTENT END marker");
  return out.replace(CONTENT_END, quoted + CONTENT_END);
}

// The same damaged region, but the document also QUOTES the probe tokens the cross-check stamps, in
// real HTML comments. A fixed token would let the document vouch for a marker that is not in a
// comment at all, so the token stem must be derived from the source and be absent from it.
function damagedEndWithQuotedProbeTokens(html) {
  const out = damagedEndQuotedInScriptText(html);
  let decoys = "";
  for (let i = 0; i < 12; i += 1) decoys += "<!-- cmhMarkerProbe" + i + "z -->\n";
  return out.replace(CONTENT_END, decoys + CONTENT_END);
}

// A marker parked in `<noscript>`. This is the one shape the cross-check must handle EXPLICITLY:
// DOMParser has scripting disabled, so it builds a real comment node there, while the live document
// a reader opens keeps the same bytes as inert text and no boundary exists. `_cmhInInertHost` is
// what keeps the two views agreeing, so a decoy here would otherwise be blessed.
function damagedEndQuotedInNoscript(html) {
  const out = html.replace(EMBED_END, "<!-- END: commentable-html - EMBEDDED COMMENTS (damaged) -->");
  if (out === html) throw new Error("fixture premise: no EMBEDDED COMMENTS END marker to damage");
  return out.replace(CONTENT_END, "<noscript>\n" + EMBED_END + "\n</noscript>\n" + CONTENT_END);
}

// An HTML comment carrying the marker but NOT on a line of its own. A LINE locator cannot see it, so
// it is neither counted nor probed, yet the strips' `<!--\s*=*\s*` prefix is not line-anchored and
// happily starts there - ahead of the real BEGIN - cutting the author's content away with the
// region. Reported by the Copilot reviewer on the PR for this issue and reproduced: the shipped
// Shareable document lost the content after such a decoy on Plain export.
function inlineBeginDecoyBeforeTheRealRegion(html) {
  const decoy = "<p>KEEPME_BEFORE</p><!-- BEGIN: commentable-html - JS -->\n<p>KEEPME_AFTER</p>\n";
  if (!html.includes(CONTENT_END)) throw new Error("fixture premise: no CONTENT END marker");
  return html.replace(CONTENT_END, decoy + CONTENT_END);
}

async function expectExportAborts(page, server, urlPath, buttonId) {  let downloadFired = false;
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

  test("Export Offline aborts on a duplicated EMBEDDED COMMENTS BEGIN marker in a nonshareable doc (F28)", async ({ page }) => {
    const staged = stageNonShareable({ companions: true, mutate: duplicateBegin });
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/NONSHAREABLE.html", "btnExportOffline");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Export Offline aborts on a duplicated EMBEDDED COMMENTS END marker in a nonshareable doc (F37)", async ({ page }) => {
    const staged = stageNonShareable({ companions: true, mutate: duplicateEnd });
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/NONSHAREABLE.html", "btnExportOffline");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });
});

// CMH-EXP-22: a marker the TEXT scan finds is only a region boundary when the document really
// parses one there. A marker-shaped line inside a raw-text body (<script>, <textarea>, <title>,
// <noscript>) is prose a reader sees, never a boundary - the validator has refused it since
// CMH-VAL-20, and the runtime export gate must give the same answer or a damaged region whose only
// marker is an authored quotation passes the gate and the strip cuts from the wrong place.
test.describe("runtime region guard refuses a marker the document does not parse as a boundary", () => {
  test("Export Plain aborts when the only EMBEDDED COMMENTS END marker is quoted in script text (CMH-EXP-22)", async ({ page }) => {
    const staged = stageInline({ mutate: damagedEndQuotedInScriptText });
    const html = fs.readFileSync(staged.html, "utf8");
    // Fixture premise: exactly one END marker LINE survives, and it is the authored quotation - so
    // a text-only count sees a well-formed region.
    const lines = html.split("\n").filter((l) => l.trim() === EMBED_END);
    expect(lines.length).toBe(1);
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/doc.html", "btnSavePlain");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Export Plain aborts when the parsed END marker is not the one the text scan found (CMH-EXP-22)", async ({ page }) => {
    // The counts agree and the markers do not: a count-only cross-check passes this document, and
    // the strip still anchors on the authored quotation.
    const staged = stageInline({ mutate: legacyCloseWithQuotedDecoy });
    const html = fs.readFileSync(staged.html, "utf8");
    const located = html.split("\n").filter((l) => l.trim() === EMBED_END);
    expect(located.length).toBe(1);
    expect(html).toContain("<!-- END: commentable-html - EMBEDDED COMMENTS --!>");
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/doc.html", "btnSavePlain");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Export Plain aborts when the only END marker is parked in a <noscript> (CMH-EXP-22)", async ({ page }) => {
    const staged = stageInline({ mutate: damagedEndQuotedInNoscript });
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/doc.html", "btnSavePlain");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Export Offline aborts on the same damaged region in a nonshareable document (CMH-EXP-22)", async ({ page }) => {
    // The gate's SECOND call site: `_inlineNonShareableAssets`, which the offline and shareable
    // exports of a companion document both reach. Only the Plain path was covered otherwise.
    const staged = stageNonShareable({ companions: true, mutate: damagedEndQuotedInScriptText });
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/NONSHAREABLE.html", "btnExportOffline");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a document that quotes the cross-check's own probe tokens cannot vouch for a phantom marker (CMH-EXP-22)", async ({ page }) => {    const staged = stageInline({ mutate: damagedEndWithQuotedProbeTokens });
    const html = fs.readFileSync(staged.html, "utf8");
    expect(html).toContain("<!-- cmhMarkerProbe0z -->");
    const server = await startStaticServer(staged.dir);
    try {
      await expectExportAborts(page, server, "/doc.html", "btnSavePlain");
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("Export Plain aborts on an inline BEGIN decoy the strip would anchor on (CMH-EXP-22)", async ({ page }) => {
    // The strip's anchor is not line-anchored, so a marker inside an HTML comment that shares its
    // line with other markup is invisible to the LINE locator and still aims the strip. Before this
    // guard the export downloaded a copy with everything after the decoy deleted.
    const staged = stageInline({ mutate: inlineBeginDecoyBeforeTheRealRegion });
    const server = await startStaticServer(staged.dir);
    let downloadFired = false;
    page.on("download", () => { downloadFired = true; });
    try {
      await page.goto(server.url + "/doc.html");
      await ready(page);
      await openToolbarMenu(page);
      await page.locator("#btnSavePlain").dispatchEvent("click");
      await page.waitForFunction(() => {
        const t = document.getElementById("toast");
        return !!t && t.classList.contains("show") && /Export aborted/.test(t.textContent || "");
      }, null, { timeout: 8000 });
      const toast = await page.evaluate(() => document.getElementById("toast").textContent || "");
      expect(toast).toContain("earlier");
      expect(toast).toContain("JS region's own BEGIN marker");
      await page.waitForTimeout(300);
      expect(downloadFired).toBe(false);
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a Shareable document whose CSS region markers live in a live <style> still exports (CMH-EXP-22)", async ({ page }) => {    // The sanctioned exception. The CSS region's markers are `/* ... */` comments inside a LIVE
    // <style>, which a browser keeps as stylesheet TEXT and never turns into a comment NODE, so a
    // parse-only rule that demanded comment nodes everywhere would abort every valid Shareable
    // export. An unmutated document must still download.
    const staged = stageInline();
    const html = fs.readFileSync(staged.html, "utf8");
    // Fixture premise: those markers really are CSS comments, not HTML comments.
    expect(html).toContain("/* ============================================================\n   BEGIN: commentable-html - CSS");
    const server = await startStaticServer(staged.dir);
    try {
      await page.goto(server.url + "/doc.html");
      await ready(page);
      await openToolbarMenu(page);
      const [download] = await Promise.all([
        page.waitForEvent("download", { timeout: 15000 }),
        page.locator("#btnSavePlain").dispatchEvent("click"),
      ]);
      expect(download.suggestedFilename()).toMatch(/\.plain\.html$/);
    } finally {
      await server.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });
});
