// CMH-EXP-16: the embedded-comments block must be resolved STRUCTURALLY (a parsed script
// element outside any raw-text body), never by scanning the document text. The layer's own
// source necessarily spells that markup, so a text scan is answered by the runtime itself:
// the "region is missing" guard could never fire, and an export of a document that had
// genuinely lost the block overwrote the runtime's own source with the comments JSON.
import { test, expect } from "@playwright/test";
import fs from "fs";
import {
  addTextComment, clickSidebarExport, currentToast, openInline, readDownload,
  ready, stageInline, startStaticServer,
} from "./helpers.js";

// Drop the REAL embedded-comments block. The first match is the real one (it precedes the
// runtime), and the throw makes a fixture that silently stopped matching fail loudly.
function removeEmbeddedBlock(html) {
  const out = html.replace(
    /<script\b[^>]*\sid="embeddedComments"[^>]*>[\s\S]*?<\/script>\s*/i, "");
  if (out === html) throw new Error("fixture: no embeddedComments block to remove");
  return out;
}

test("Export as Shareable fails loudly when the embedded-comments block is missing (CMH-EXP-16)", async ({ page }) => {
  const staged = stageInline({ mutate: removeEmbeddedBlock });
  const server = await startStaticServer(staged.dir);
  try {
    await page.goto(server.url + "/doc.html");
    await ready(page);
    await addTextComment(page, "#commentRoot p", "note that must not be exported");
    let gotDownload = false;
    page.once("download", () => { gotDownload = true; });
    await clickSidebarExport(page, "#btnSaveHtml");
    await expect.poll(() => currentToast(page)).toContain("EMBEDDED COMMENTS region is present");
    // Nothing was downloaded: no export ever rewrites the layer's own source in place of
    // the missing block.
    expect(gotDownload).toBe(false);
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("the embedded-comments block is resolved structurally, never from script-body text (CMH-EXP-16)", async ({ page }) => {
  await openInline(page);
  const out = await page.evaluate(() => {
    const OPEN = "<scr" + "ipt";
    const CLOSE = "</scr" + "ipt>";
    const MENTION = OPEN + ' id="embeddedComments">';
    // A document whose ONLY mention sits inside a script body - the shape of the layer itself.
    const layerOnly = "<html><body>" + OPEN + ">\n// writes into " + MENTION
      + "\nvar x = 1;\n" + CLOSE + "</body></html>";
    // The same mention FIRST, a real block after it: the real one must win.
    const real = OPEN + ' type="application/json" id="embeddedComments">[1]' + CLOSE;
    const both = "<html><body>" + OPEN + ">\n// mentions " + MENTION + "\n" + CLOSE
      + "\n" + real + "</body></html>";
    // A decoy attribute is not an id.
    const decoy = "<html><body>" + OPEN + ' data-id="embeddedComments">[2]' + CLOSE
      + "</body></html>";
    const r = window.__cmhFindEmbeddedComments(both);
    return {
      layerOnly: window.__cmhFindEmbeddedComments(layerOnly),
      decoy: window.__cmhFindEmbeddedComments(decoy),
      resolved: r ? both.slice(r.start, r.end) : null,
    };
  });
  expect(out.layerOnly).toBe(null);
  expect(out.decoy).toBe(null);
  expect(out.resolved).toBe('<script type="application/json" id="embeddedComments">[1]</script>');
});

test("a fetched copy is not accepted on the strength of a layer-JS mention (CMH-EXP-16)", async ({ page }) => {
  const staged = stageInline();
  const server = await startStaticServer(staged.dir);
  try {
    await page.goto(server.url + "/doc.html");
    await ready(page);
    await addTextComment(page, "#commentRoot p", "snapshot-note");
    // The copy the runtime re-fetches at export time has LOST its embedded-comments block;
    // its only remaining mention of one is inside the layer's own script body. That copy is
    // unusable as a base, so the export must fall back to the DOM snapshot instead.
    const corrupted = removeEmbeddedBlock(fs.readFileSync(staged.html, "utf8"))
      .replace("</body>", "<!-- FETCHED_COPY_SENTINEL -->\n</body>");
    await page.route(server.url + "/doc.html", (route) => route.fulfill({
      status: 200, contentType: "text/html", body: corrupted,
    }));
    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const html = await readDownload(dl);
    expect(html).not.toContain("FETCHED_COPY_SENTINEL");
    expect(html).toContain("snapshot-note");
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});
