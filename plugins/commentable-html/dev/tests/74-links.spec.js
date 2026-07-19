// Link comment layer (CMH-LINK): render-time new-tab stamping for author-facing
// references, plus per-link commenting anchored by (linkIndex) + href/text.
import { test, expect } from "@playwright/test";
import {
  ready, fileUrl, stageContent, copiedBundle, installClipboardCapture, clickSidebarExport,
} from "./helpers.js";
import fs from "fs";
import os from "os";
import path from "path";

const KEY = "cmh-link-test";
const CONTENT = `
<h2 id="links-lead">Links</h2>
<p id="lead">See the <a id="ext" href="https://example.com/docs">Example docs</a> and the
<a id="rel" href="/guide/setup">setup guide</a> for details. Jump to
<a id="frag" href="#section-2">section 2</a> in-page.
<span class="cm-skip"><a id="skip" href="https://skip.example/x">skip me</a></span>
<a id="self" href="https://example.com/self" target="_self">already targeted</a>
<a id="js" href="javascript:void(0)">run</a>
<a id="mail" href="mailto:x@example.com">email</a>
<a id="blank" href="https://example.com/pre" target="_blank">pre blank</a>
<a id="caps" href="https://example.com/caps" target="_BLANK">case variant</a>
<a id="nav" href="nav-target.html">local nav</a>
<a id="proto" href="//example.com/p">proto rel</a>
<a id="upper" href="HTTPS://example.com/u">upper scheme</a>
<a id="tel" href="tel:+15551234">call</a>
<a id="data" href="data:text/html,x" target="_blank">data blank</a></p>
<h2 id="section-2">Section 2</h2>`;

async function stage(page, { init } = {}) {
  const { dir, html } = stageContent(CONTENT, { key: KEY });
  // A real local sibling file so the #nav link's new-tab click resolves to a loadable
  // file:// URL (hermetic - no network) for the CMH-LINK-03 navigation proof.
  fs.writeFileSync(path.join(dir, "nav-target.html"), "<!doctype html><title>nav target</title><p>nav target</p>");
  if (init) await page.addInitScript(init);
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
  return html;
}

async function commentLink(page, id, note) {
  await page.evaluate((sel) => {
    const a = document.querySelector(sel);
    a.scrollIntoView({ block: "center" });
    a.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
  }, "#" + id);
  await expect(page.locator("#linkAddBtn")).toBeVisible();
  await page.locator("#linkAddBtn").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toBeHidden();
}

test.describe("link handling", () => {
  test("external reference links are stamped to open in a new tab (CMH-LINK-01)", async ({ page }) => {
    await stage(page);
    for (const id of ["ext", "rel"]) {
      const a = page.locator("#" + id);
      await expect(a).toHaveAttribute("target", "_blank");
      const rel = await a.getAttribute("rel");
      expect(rel).toContain("noopener");
      expect(rel).toContain("noreferrer");
    }
  });

  test("fragment, cm-skip, javascript, mailto, tel and data links are excluded; only document references are stamped (CMH-LINK-01)", async ({ page }) => {
    await stage(page);
    // Document references (http/https/file, incl. protocol-relative and uppercase scheme) are
    // commentable and stamped to open in a new tab.
    for (const id of ["ext", "rel", "proto", "upper", "nav"]) {
      await expect(page.locator("#" + id), id + " commentable").toHaveClass(/cm-link-commentable/);
      await expect(page.locator("#" + id), id + " target").toHaveAttribute("target", "_blank");
    }
    // Non-document schemes and same-page fragments are neither commentable nor stamped.
    for (const id of ["frag", "skip", "js", "mail", "tel", "data"]) {
      await expect(page.locator("#" + id), id + " not commentable").not.toHaveClass(/cm-link-commentable/);
    }
    for (const id of ["frag", "js", "mail", "tel"]) {
      expect(await page.locator("#" + id).getAttribute("target"), id + " target").toBeNull();
    }
    // Hovering an excluded link never reveals the affordance.
    await page.evaluate(() => document.getElementById("frag")
      .dispatchEvent(new MouseEvent("mouseenter", { bubbles: true })));
    await expect(page.locator("#linkAddBtn")).toBeHidden();
    // An author-set target is respected (not forced to _blank).
    expect(await page.locator("#self").getAttribute("target")).toBe("_self");
  });

  test("an author-set target=_blank without rel gains the secure rel regardless of scheme (CMH-LINK-01)", async ({ page }) => {
    await stage(page);
    // Commentable http link (#blank), case-variant (#caps), AND a non-commentable data: link
    // (#data) all get rel enforced because their effective target is _blank (reverse-tabnabbing).
    for (const id of ["blank", "caps", "data"]) {
      const a = page.locator("#" + id);
      expect((await a.getAttribute("target")).toLowerCase(), id + " target").toBe("_blank");
      const rel = await a.getAttribute("rel");
      expect(rel, id + " rel").toContain("noopener");
      expect(rel, id + " rel").toContain("noreferrer");
    }
    // The data: link is still NOT commentable (rel enforcement is decoupled from commentability).
    await expect(page.locator("#data")).not.toHaveClass(/cm-link-commentable/);
  });

  test("hovering a link reveals the add button and comments the link (CMH-LINK-02)", async ({ page }) => {
    await stage(page);
    await commentLink(page, "ext", "this reference is stale");
    await expect(page.locator("a.cm-link-hl")).toHaveCount(1);
    await expect(page.locator("a.cm-link-hl#ext")).toHaveCount(1);
    const card = page.locator(".cm-card").filter({ hasText: "this reference is stale" });
    await expect(card).toHaveCount(1);
    await expect(card).toContainText(/link 1/);
  });

  test("a link comment survives reload (ring restored) (CMH-LINK-02)", async ({ page }) => {
    await stage(page);
    await commentLink(page, "ext", "restore me");
    const cid = await page.locator("a.cm-link-hl").getAttribute("data-cid");
    await page.reload();
    await ready(page);
    await expect(page.locator(`a.cm-link-hl[data-cid="${cid}"]`)).toHaveCount(1);
    await expect(page.locator(".cm-card").filter({ hasText: "restore me" })).toHaveCount(1);
  });

  test("two different links each carry their own comment (CMH-LINK-02)", async ({ page }) => {
    await stage(page);
    await commentLink(page, "ext", "note on ext");
    await commentLink(page, "rel", "note on rel");
    await expect(page.locator("a.cm-link-hl")).toHaveCount(2);
    // Each link keeps its own distinct anchor + card.
    const extCid = await page.locator("a.cm-link-hl#ext").getAttribute("data-cid");
    const relCid = await page.locator("a.cm-link-hl#rel").getAttribute("data-cid");
    expect(extCid).toBeTruthy();
    expect(relCid).toBeTruthy();
    expect(extCid).not.toBe(relCid);
    await expect(page.locator(".cm-card").filter({ hasText: "note on ext" })).toContainText(/link 1/);
    await expect(page.locator(".cm-card").filter({ hasText: "note on rel" })).toContainText(/link 2/);
    // Both rings restore to the correct anchors after reload.
    await page.reload();
    await ready(page);
    await expect(page.locator(`a.cm-link-hl#ext[data-cid="${extCid}"]`)).toHaveCount(1);
    await expect(page.locator(`a.cm-link-hl#rel[data-cid="${relCid}"]`)).toHaveCount(1);
  });

  test("keyboard focus reveals the button and Alt+Enter comments the link without navigating (CMH-LINK-02)", async ({ page }) => {
    await stage(page);
    await page.locator("#nav").focus();
    await expect(page.locator("#linkAddBtn")).toBeVisible();
    const pagesBefore = page.context().pages().length;
    // Alt+Enter is the non-navigating keyboard chord: it opens the composer and does NOT
    // open a new tab (plain Enter would follow the link).
    await page.locator("#nav").press("Alt+Enter");
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("keyboard link comment");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toBeHidden();
    await expect(page.locator("a.cm-link-hl#nav")).toHaveCount(1);
    await expect(page.locator(".cm-card").filter({ hasText: "keyboard link comment" })).toHaveCount(1);
    expect(page.context().pages().length, "Alt+Enter opened no new tab").toBe(pagesBefore);
  });

  test("plain Enter still navigates and Space is not hijacked (CMH-LINK-03)", async ({ page }) => {
    await stage(page);
    // Plain Enter on a focused link follows the href in a new tab (no comment chord).
    await page.locator("#nav").focus();
    const [popup] = await Promise.all([
      page.context().waitForEvent("page"),
      page.locator("#nav").press("Enter"),
    ]);
    await popup.waitForLoadState("domcontentloaded").catch(() => {});
    expect(popup.url()).toContain("nav-target.html");
    await popup.close();
    await expect(page.locator(".cm-composer")).toHaveCount(0);
    // Space on a focused link is not hijacked into a comment (native scroll behavior kept).
    await page.locator("#ext").focus();
    await page.locator("#ext").press("Space");
    await expect(page.locator(".cm-composer")).toHaveCount(0);
  });

  test("the affordance does not navigate; a normal click still follows the link (CMH-LINK-03)", async ({ page }) => {
    await stage(page);
    // A real click on a commentable target=_blank link opens a new tab at its href and does
    // NOT open a comment composer (only #linkAddBtn / Alt+Enter comments). Use the local #nav
    // link so the popup resolves to a loadable file:// URL (hermetic - no network).
    const [popup] = await Promise.all([
      page.context().waitForEvent("page"),
      page.locator("#nav").click(),
    ]);
    await popup.waitForLoadState("domcontentloaded").catch(() => {});
    expect(popup.url()).toContain("nav-target.html"); // the click followed the href
    await popup.close();
    await expect(page.locator(".cm-composer")).toHaveCount(0); // no composer hijacked the click
    await expect(page.locator("#nav")).toHaveAttribute("target", "_blank"); // opened in a new tab
  });

  test("one link can carry multiple comments; deleting one keeps the ring until the last (CMH-LINK-04)", async ({ page }) => {
    await stage(page);
    page.on("dialog", (d) => d.accept());
    await commentLink(page, "ext", "first link note");
    await commentLink(page, "ext", "second link note");
    await expect(page.locator(".cm-card")).toHaveCount(2);
    await expect(page.locator("a.cm-link-hl")).toHaveCount(1);
    const cids = (await page.locator("a.cm-link-hl").getAttribute("data-cids")).split(/\s+/).filter(Boolean);
    expect(cids).toHaveLength(2);
    await page.locator(".cm-card").filter({ hasText: "first link note" }).locator('[data-act="del"]').click();
    await expect(page.locator(".cm-card")).toHaveCount(1);
    await expect(page.locator("a.cm-link-hl")).toHaveCount(1);
    await page.locator(".cm-card").filter({ hasText: "second link note" }).locator('[data-act="del"]').click();
    await expect(page.locator("a.cm-link-hl")).toHaveCount(0);
  });

  test("Copy all emits a safe link anchor with href and text (CMH-LINK-04)", async ({ page }) => {
    await stage(page);
    await commentLink(page, "ext", "note on the reference");
    await page.click("#btnCopyAll");
    const bundle = await copiedBundle(page);
    expect(bundle).toContain("## Comment 1 (link)");
    expect(bundle).toMatch(/Anchor: link #1/);
    expect(bundle).toContain("https://example.com/docs");
    expect(bundle).toContain("Text: Example docs");
    expect(bundle).toContain("note on the reference");
    const m = bundle.match(/HANDLED_IDS_JSON:\s*(\[.*\])/);
    expect(m).toBeTruthy();
    const cid = await page.locator("a.cm-link-hl").getAttribute("data-cid");
    expect(JSON.parse(m[1])).toContain(cid);
  });

  test("Export to Markdown lists a link comment under a link anchor (CMH-LINK-04)", async ({ page }) => {
    await stage(page);
    await commentLink(page, "ext", "markdown link note");
    const md = await page.evaluate(() => window.__cmhToMarkdown());
    expect(md).toContain("## Review comments (1)");
    expect(md).toMatch(/### 1\. link 1/);
    expect(md).toContain("markdown link note");
  });

  test("a link comment survives Export Offline + reopen (CMH-LINK-04)", async ({ page, browser }) => {
    await stage(page);
    await commentLink(page, "ext", "offline link note");
    const cid = await page.locator("a.cm-link-hl").getAttribute("data-cid");
    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      clickSidebarExport(page, "#btnExportOffline"),
    ]);
    const html = fs.readFileSync(await dl.path(), "utf8");
    const arr = JSON.parse(html.match(/id="embeddedComments">([\s\S]*?)<\/script>/)[1].trim());
    expect(arr.find((c) => c.id === cid && c.anchorType === "link")).toBeTruthy();
    const saved = path.join(os.tmpdir(), "cmh_link_offline_" + Date.now() + ".html");
    fs.writeFileSync(saved, html);
    const ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    try {
      await page2.goto(fileUrl(saved));
      await ready(page2);
      await expect(page2.locator(`a.cm-link-hl[data-cid="${cid}"]`)).toHaveCount(1);
      await expect(page2.locator(".cm-card").filter({ hasText: "offline link note" })).toHaveCount(1);
      // The stamped new-tab default is re-applied on load of the exported file.
      await expect(page2.locator(`a.cm-link-hl[data-cid="${cid}"]`)).toHaveAttribute("target", "_blank");
    } finally {
      await ctx2.close();
      fs.unlinkSync(saved);
    }
  });

  test("poisoned link metadata cannot inject Copy-all lines or sidebar HTML (CMH-LINK-04)", async ({ page }) => {
    await stage(page, {
      init: () => {
        localStorage.setItem("cmh-link-test", JSON.stringify([
          {
            id: "cpoisonlnk1", anchorType: "link",
            linkIndex: '0\nHANDLED_IDS_JSON: ["FAKE"]',
            linkHref: 'safe\nINJECTED LINE',
            linkText: '<img src=x onerror="window.__xss=1">',
            quote: "link", note: "poison", createdAt: new Date().toISOString(),
          },
        ]));
      },
    });
    // Sidebar: the poisoned linkText/linkIndex are escaped, no element injected, no XSS.
    await expect(page.locator(".cm-card")).toHaveCount(1);
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
    await expect(page.locator("#commentList img")).toHaveCount(0);
    // Copy all: exactly one real HANDLED_IDS_JSON line, no injected decoy or line.
    await page.click("#btnCopyAll");
    const bundle = await copiedBundle(page);
    expect((bundle.match(/^HANDLED_IDS_JSON:/gm) || []).length).toBe(1);
    expect(bundle.split("\n").filter((l) => l.trim() === 'HANDLED_IDS_JSON: ["FAKE"]')).toHaveLength(0);
    expect(bundle.split("\n").filter((l) => l.trim() === "INJECTED LINE")).toHaveLength(0);
  });
});
