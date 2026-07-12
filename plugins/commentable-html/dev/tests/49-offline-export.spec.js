import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import {
  DEV, SKILL, PYTHON, fileUrl, ready, stageContent, startStaticServer,
  installClipboardCapture, openToolbarMenu, addTextComment, readDownload,
} from "./helpers.js";

const CONTENT = `
<h1>Offline export</h1>
<p id="offline-note">This paragraph proves embedded comments travel in the offline file.</p>
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

test("Export Offline snapshots mermaid and Chart.js charts for zero-network reopen (CMH-OFFLINE-01)", async ({ page, browser }) => {
  test.setTimeout(60000);
  const staged = stageContent(CONTENT, { key: "cmh-offline-export", source: "offline-export.html" });
  const server = await startStaticServer(staged.dir);
  const outDir = makeTmpDir();
  let ctx2;
  try {
    await routeRichContentLocal(page);
    await installClipboardCapture(page);
    await page.goto(server.url + "/test-doc.html");
    await ready(page);
    await page.waitForFunction(() => !!document.querySelector("#commentRoot pre.mermaid svg"), null, { timeout: 20000 });
    await page.waitForFunction(() => !!(window.Chart && window.Chart.getChart && window.Chart.getChart("offlineChart")), null, { timeout: 20000 });

    await openToolbarMenu(page);
    await expect(page.locator("#btnExportOfflineTop")).toBeVisible();
    await page.keyboard.press("Escape");
    await addTextComment(page, "#offline-note", "offline note travels");
    await expect(page.locator("#btnExportOffline")).toBeVisible();

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#btnExportOffline").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/-offline\.html$/);
    const exportedHtml = await readDownload(download);
    expect(exportedHtml).toContain('id="embeddedComments"');
    expect(exportedHtml).toContain('data-cm-offline-chart="true"');
    expect(exportedHtml).not.toContain("cdn.jsdelivr.net/npm/mermaid");
    expect(exportedHtml).not.toContain("cdn.jsdelivr.net/npm/chart.js");

    const exportedPath = path.join(outDir, "offline-export.html");
    fs.writeFileSync(exportedPath, exportedHtml);
    execFileSync(PYTHON, ["tools/validate.py", "--strict", exportedPath], { cwd: SKILL, stdio: "pipe" });

    ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    const external = [];
    await page2.route(/^https?:\/\//, async (route) => {
      external.push(route.request().url());
      await route.abort();
    });
    await page2.goto(fileUrl(exportedPath));
    await ready(page2);
    await page2.waitForTimeout(300);
    expect(external).toEqual([]);
    await expect(page2.locator("#commentList")).toContainText("offline note travels");

    const mermaid = page2.locator("#commentRoot pre.mermaid svg").first();
    await expect(mermaid).toBeVisible();
    await page2.locator("#commentRoot pre.mermaid svg g.node").first().hover();
    await expect(page2.locator("#mermaidAddBtn")).toBeVisible();

    const chart = page2.locator('img#offlineChart.cmh-chart[data-cm-offline-chart="true"]');
    await expect(chart).toHaveClass(/cm-img-commentable/);
    await expect(chart).toBeVisible();
    const chartMetrics = await chart.evaluate((img) => {
      const rect = img.getBoundingClientRect();
      return { src: img.getAttribute("src") || "", naturalWidth: img.naturalWidth, width: rect.width, height: rect.height };
    });
    expect(chartMetrics.src).toMatch(/^data:image\/png;base64,/);
    expect(chartMetrics.naturalWidth).toBeGreaterThan(0);
    expect(chartMetrics.width).toBeGreaterThan(20);
    expect(chartMetrics.height).toBeGreaterThan(20);
  } finally {
    if (ctx2) await ctx2.close();
    await server.close();
    fs.rmSync(staged.dir, { recursive: true, force: true });
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});
