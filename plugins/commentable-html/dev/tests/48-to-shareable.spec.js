import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import {
  PYTHON, SKILL, addTextComment, fileUrl, installClipboardCapture, lastCopied, ready,
  stageNonShareable,
} from "./helpers.js";

// CMH-PORT-04. Everything about the migration had been verified by reading the produced bytes.
// The promise a user cares about is different: the migrated file OPENS and behaves like a
// natively generated Shareable one, and a document migrated with an untrusted `--dist` does not
// execute what that dist smuggled in. Both are only observable in a browser.

function migrate(htmlPath, extraArgs = []) {
  execFileSync(PYTHON, ["tools/authoring/to_shareable.py", ...extraArgs, htmlPath], { cwd: SKILL });
}

test.describe("to_shareable migration", () => {
  test("a migrated document opens, comments and copies like a native Shareable one (CMH-PORT-04)", async ({ page }) => {
    const { html, dir } = stageNonShareable();
    try {
      migrate(html);
      // The companions are what a NonShareable document needs beside it; deleting them proves the
      // migrated file is genuinely self-contained rather than quietly still loading them.
      for (const f of fs.readdirSync(dir)) {
        if (/^commentable-html\.(css|js|assets\.js)$/.test(f)) fs.rmSync(path.join(dir, f));
      }
      await installClipboardCapture(page);
      await page.goto(fileUrl(html));
      await ready(page);

      await expect(page.locator("#cmhModeBadge")).toHaveText("Shareable");
      expect(await page.evaluate(() => document.body.classList.contains("cm-nonshareable"))).toBe(false);
      await expect(page.locator("#cmhAssetBanner")).toBeHidden();

      await addTextComment(page, "#commentRoot section p", "note on a migrated document");
      await expect(page.locator("#toolbarCount")).toHaveText("1");
      await page.click("#btnCopyAll");
      expect(await lastCopied(page)).toContain("note on a migrated document");
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("a hostile dist cannot execute script in a migrated document (CMH-PORT-04)", async ({ page }) => {
    const { html, dir } = stageNonShareable();
    const hostile = fs.mkdtempSync(path.join(dir, "dist-"));
    try {
      for (const f of ["commentable-html.css", "commentable-html.js", "commentable-html.assets.js"]) {
        fs.copyFileSync(path.join(SKILL, "dist", f), path.join(hostile, f));
      }
      // Control of the STYLESHEET alone must not escalate to script execution: inserted verbatim,
      // this closes the <style> element and everything after it parses as live markup.
      const cssPath = path.join(hostile, "commentable-html.css");
      fs.appendFileSync(cssPath, "\nbody{}\n</StYlE><script>window.cmhPwnedMarker=1;</script><style>\n");
      migrate(html, ["--dist", hostile]);

      await page.goto(fileUrl(html));
      await ready(page);
      expect(await page.evaluate(() => window.cmhPwnedMarker), "the smuggled script must not run").toBeUndefined();
      // Neutralized, not dropped: the text is still there, inert inside the stylesheet.
      expect(fs.readFileSync(html, "utf8")).toContain("window.cmhPwnedMarker=1");
      expect(await page.evaluate(() => document.querySelectorAll("script[src]").length)).toBe(0);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
