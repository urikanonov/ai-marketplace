import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import {
  openInline, addTextComment, distinctCids, lastCopied, fileUrl, stageInline, SKILL,
} from "./helpers.js";

test.describe("Copy all + handled-id pruning", () => {
  test("Copy all emits the markdown bundle with an exact HANDLED_IDS_JSON line", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot section p", "reviewer note here");
    const cid = await page.locator("mark.cm-hl").first().getAttribute("data-cid");
    await page.locator("#btnCopyAll").click(); // sidebar Copy all (toolbar hides while the panel is open)
    const bundle = await lastCopied(page);
    expect(bundle).toBeTruthy();
    expect(bundle).toContain("reviewer note here");
    const m = bundle.match(/HANDLED_IDS_JSON:\s*(\[.*\])/);
    expect(m, "bundle has a HANDLED_IDS_JSON line").toBeTruthy();
    expect(JSON.parse(m[1])).toEqual([cid]);
  });

  test("marking an id handled prunes it on reload and from Copy all (via mark_handled.py)", async ({ page }) => {
    const { html, dir } = stageInline();
    try {
      await page.addInitScript(() => {
        window.__copied = [];
        const c = navigator.clipboard;
        if (c && c.writeText) { const o = c.writeText.bind(c); c.writeText = (t) => { window.__copied.push(String(t)); try { return o(t).catch(() => {}); } catch (e) { return Promise.resolve(); } }; }
      });
      await page.goto(fileUrl(html));
      await page.waitForFunction(() => window.__commentableHtmlReady === true);

      // Two comments; exactly one gets marked handled so Copy all must still emit the
      // OTHER (proves the bundle is real, not just null after pruning to zero).
      await addTextComment(page, "#commentRoot section p", "will be handled", 0);
      await addTextComment(page, "#commentRoot section p", "stays unhandled", 1);
      const cids = await page.$$eval("mark.cm-hl", (els) => [...new Set(els.map((e) => e.dataset.cid))]);
      expect(cids.length).toBe(2);
      const handledCid = cids[0];
      const keptCid = cids[1];

      // Simulate the agent's iteration step with the real helper.
      execFileSync("python", ["tools/mark_handled.py", html, handledCid], { cwd: SKILL });
      expect(fs.readFileSync(html, "utf8")).toContain(handledCid);

      await page.reload();
      await page.waitForFunction(() => window.__commentableHtmlReady === true);
      expect(await distinctCids(page)).toBe(1);
      await expect(page.locator("#toolbarCount")).toHaveText("1");

      await page.click("#btnCopyAll"); // panel open (one live comment) -> sidebar Copy all
      const bundle = await lastCopied(page);
      expect(bundle, "a real bundle was copied").toBeTruthy();
      expect(bundle).toContain("stays unhandled");
      expect(bundle).toContain(keptCid);
      expect(bundle).not.toContain(handledCid);
      expect(bundle).not.toContain("will be handled");
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
