#!/usr/bin/env node
import fs from "node:fs";
import { parseArgs } from "node:util";
import { chromium } from "@playwright/test";
import { stageContent, fileUrl, denyExternalNetwork } from "../tests/helpers.js";

const { values } = parseArgs({ options: {
  counts: { type: "string", default: "50,150,393" },
  layouts: { type: "string", default: "block,flex,grid" },
  cpu: { type: "string", default: "1,4" },
  runs: { type: "string", default: "3" },
} });
const counts = values.counts.split(",").map(Number);
const rates = values.cpu.split(",").map(Number);
const layouts = values.layouts.split(",");
const runs = Number(values.runs);
if (![...counts, runs].every((n) => Number.isInteger(n) && n > 0) ||
    !rates.every((n) => Number.isFinite(n) && n >= 1) ||
    !layouts.every((name) => ["block", "flex", "grid"].includes(name))) {
  throw new Error("Use positive integer counts/runs, CPU rates >= 1, and block,flex,grid layouts");
}
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const count of counts) for (const layout of layouts) {
    const cells = (tag, row) => Array.from({ length: 8 }, (_, c) =>
      `<${tag}>${row} ${c}</${tag}>`).join("");
    const table = `<table><thead><tr>${cells("th", "Column")}</tr></thead><tbody>` +
      Array.from({ length: 6 }, (_, r) => `<tr>${cells("td", `Cell ${r}`)}</tr>`).join("") +
      "</tbody></table>";
    const display = layout === "block" ? "" :
      ` style="display:${layout};${layout === "grid" ? "grid-template-columns:repeat(4,1fr)" : "flex-wrap:wrap"}"`;
    const staged = stageContent("<h1>Synthetic CMH table startup benchmark</h1>" +
      Array.from({ length: count }, (_, i) =>
        `<section><h2>Section ${i}</h2><div${display}>${table}</div></section>`).join(""),
    { key: "cmh-table-startup-benchmark" });
    try {
      const html = fs.readFileSync(staged.html, "utf8");
      const call = "\nsetupTableScroll();";
      if (html.split(call).length !== 2) throw new Error("Expected one table-scroll startup call");
      fs.writeFileSync(staged.html, html.replace(call,
        '\nperformance.mark("table-start");setupTableScroll();' +
        'performance.mark("table-end");performance.measure("table-setup","table-start","table-end");'));
      for (const cpu of rates) for (let run = 1; run <= runs; run++) {
        const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
        try {
          const page = await context.newPage();
          const errors = [];
          page.on("pageerror", (e) => errors.push(e.message));
          await denyExternalNetwork(page);
          const cdp = await context.newCDPSession(page);
          await cdp.send("Emulation.setCPUThrottlingRate", { rate: cpu });
          await page.goto(fileUrl(staged.html), { waitUntil: "load", timeout: 180000 });
          await page.waitForFunction(() => performance.getEntriesByName("first-contentful-paint").length > 0);
          const metrics = await page.evaluate(() => ({
            setupMs: performance.getEntriesByName("table-setup")[0].duration,
            loadMs: performance.getEntriesByType("navigation")[0].loadEventEnd,
            firstContentfulPaintMs: performance.getEntriesByName("first-contentful-paint")[0].startTime,
            tables: document.querySelectorAll("#commentRoot table").length,
            wrappers: document.querySelectorAll("#commentRoot .cmh-table-scroll").length,
          }));
          if (errors.length || page.__external.length || metrics.tables !== count || metrics.wrappers !== count) {
            throw new Error(JSON.stringify({ errors, external: page.__external, metrics }));
          }
          const sample = { count, layout, cpuThrottlingRate: cpu, run, ...metrics };
          results.push(sample);
          console.error(JSON.stringify(sample));
        } finally { await context.close(); }
      }
    } finally { fs.rmSync(staged.dir, { recursive: true, force: true }); }
  }
  console.log(JSON.stringify({ browser: browser.version(), platform: process.platform, results }, null, 2));
} finally { await browser.close(); }
