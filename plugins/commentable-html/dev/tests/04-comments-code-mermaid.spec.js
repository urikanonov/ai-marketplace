import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import { PYTHON } from "./helpers.js";
import fs from "fs";
import path from "path";
import {
  openInline, addTextComment, installClipboardCapture, ready,
  startStaticServer, routeMermaidLocal, stageInline, SKILL,
} from "./helpers.js";

test.describe("code comments", () => {
  test("commenting on a code block tags the card as code", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot pre code", "tighten this loop");
    await expect(page.locator("#commentList")).toContainText("tighten this loop");
    // The demo code block is class="language-python" -> pin reads "code (python)".
    await expect(page.locator(".cm-card .pin")).toContainText(/code/i);
  });
});

// Mermaid's CDN ES-module import is blocked over file://, so serve over http; the
// jsdelivr request is intercepted and served from the locally vendored mermaid,
// so the diagram renders with no network access (fully deterministic).
test.describe("mermaid node comments (local vendored mermaid)", () => {
  test("hovering a node reveals + Add comment; saving anchors and rings the node", async ({ page }) => {
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/TEMPLATE.html?mermaid=1");
      await ready(page);

      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });

      await node.hover();
      await expect(page.locator("#mermaidAddBtn")).toBeVisible();
      await page.locator("#mermaidAddBtn").click();

      const composer = page.locator(".cm-composer").last();
      await expect(composer).toBeVisible();
      await composer.locator("textarea").fill("rename this node");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);

      await expect(page.locator("#commentList")).toContainText("rename this node");
      await expect(page.locator(".cm-card .pin")).toContainText(/mermaid diagram/i);
      await expect(page.locator("#commentRoot .mermaid .cm-mermaid-hl").first()).toBeVisible();
    } finally {
      await server.close();
    }
  });

  test("a mermaid node can carry multiple comments; delete-one keeps the ring, reload restores both", async ({ page }) => {
    const server = await startStaticServer(SKILL);
    try {
      await routeMermaidLocal(page);
      await page.goto(server.url + "/TEMPLATE.html?mermaid=1");
      await ready(page);
      page.on("dialog", (d) => d.accept());
      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });

      const addOn = async (note) => {
        await node.hover();
        await expect(page.locator("#mermaidAddBtn")).toBeVisible();
        await page.locator("#mermaidAddBtn").click();
        const composer = page.locator(".cm-composer").last();
        await composer.locator("textarea").fill(note);
        await composer.locator('[data-act="save"]').click();
        await expect(composer).toHaveCount(0);
      };
      await addOn("first mermaid note");
      await addOn("second mermaid note");

      const cids = (await page.locator("#commentRoot .mermaid .cm-mermaid-hl").first()
        .getAttribute("data-cids")).split(/\s+/).filter(Boolean);
      expect(cids).toHaveLength(2);
      await expect(page.locator(".cm-card")).toHaveCount(2);

      // Delete one -> the ring remains for the survivor.
      await page.locator(".cm-card").filter({ hasText: "first mermaid note" }).locator('[data-act="del"]').click();
      await expect(page.locator("#commentRoot .mermaid .cm-mermaid-hl")).toHaveCount(1);
      await expect(page.locator(".cm-card")).toHaveCount(1);

      // Two comments on the node again -> both survive reload/re-render.
      await addOn("third mermaid note");
      await page.reload();
      await ready(page);
      await expect(page.locator("#commentRoot .mermaid svg g.node").first()).toBeVisible({ timeout: 20000 });
      await expect(page.locator(".cm-card")).toHaveCount(2);
      const after = (await page.locator("#commentRoot .mermaid .cm-mermaid-hl").first()
        .getAttribute("data-cids")).split(/\s+/).filter(Boolean);
      expect(after).toHaveLength(2);
    } finally {
      await server.close();
    }
  });

  test("a mermaid comment prunes on reload once marked handled", async ({ page }) => {
    let server, dir, html;
    try {
      const staged = stageInline();
      dir = staged.dir; html = staged.html;
      server = await startStaticServer(dir);
      await routeMermaidLocal(page);
      await installClipboardCapture(page);
      await page.goto(server.url + "/" + path.basename(html) + "?mermaid=1");
      await ready(page);

      const node = page.locator("#commentRoot .mermaid svg g.node").first();
      await expect(node).toBeVisible({ timeout: 20000 });
      await node.hover();
      await page.locator("#mermaidAddBtn").click();
      const composer = page.locator(".cm-composer").last();
      await composer.locator("textarea").fill("mermaid to prune");
      await composer.locator('[data-act="save"]').click();
      await expect(composer).toHaveCount(0);

      const cid = await page.locator(".cm-card").first().getAttribute("data-cid");
      execFileSync(PYTHON, ["tools/mark_handled.py", html, cid], { cwd: SKILL });

      await page.reload();
      await ready(page);
      await expect(page.locator("#commentRoot .mermaid svg g.node").first()).toBeVisible({ timeout: 20000 });
      await expect(page.locator("#commentList")).not.toContainText("mermaid to prune");
      await expect(page.locator("#toolbarCount")).toHaveText("0");
      await expect(page.locator("#commentRoot .mermaid .cm-mermaid-hl")).toHaveCount(0);
      await expect(page.locator("#cmhAssetBanner")).toBeHidden();
    } finally {
      if (server) await server.close();
      if (dir) fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
