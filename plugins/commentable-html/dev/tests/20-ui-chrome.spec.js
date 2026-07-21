// Sidebar version indicator, document-type bubble, Help dialog, per-button tooltips,
// and the wide-screen table-of-contents side menu (scroll-spy, collapse, back-to-top).
import { test, expect } from "@playwright/test";
import { openInline, openNonPortable, openToolbarMenu, addTextComment, ready, fileUrl, stageInline, readDownload, INLINE } from "./helpers.js";
import fs from "fs";

test.describe("UI chrome: version, type bubble, help, TOC side menu", () => {
  test("the sidebar/menu toggles declare the element they control via aria-controls (CMH-A11Y-06)", async ({ page }) => {
    await openInline(page);
    // The overflow-menu trigger points at the menu it opens.
    const menuBtn = page.locator("#btnToolbarMenu");
    await expect(menuBtn).toHaveAttribute("aria-controls", "toolbarMenu");
    await expect(menuBtn).toHaveAttribute("aria-haspopup", "true");
    await expect(page.locator("#toolbarMenu")).toHaveCount(1);
    // The sidebar show/hide toggle points at the comments panel it controls.
    const sidebarBtn = page.locator("#btnToggleSidebar");
    await expect(sidebarBtn).toHaveAttribute("aria-controls", "sidebar");
    await expect(sidebarBtn).toHaveAttribute("aria-expanded", /^(true|false)$/);
    await expect(page.locator("#sidebar")).toHaveCount(1);
  });

  test("the sidebar shows the layer version", async ({ page }) => {
    await openInline(page);
    await expect(page.locator("#cmVersion")).toHaveText(/^v\d+\.\d+\.\d+$/);
  });

  test("the type bubble reads Portable for an inline document with no comments", async ({ page }) => {
    await openInline(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
  });

  test("adding a not-yet-embedded comment makes the type Not portable", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "a fresh comment lives only in storage");
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");
    // The bubble explains WHY it is not portable.
    await expect(page.locator("#cmTypeBadge")).toHaveAttribute("title", /not embedded/i);
  });

  test("the type bubble reads Not portable for an nonportable document", async ({ page }) => {
    await openNonPortable(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");
    await expect(page.locator("#cmTypeBadge")).toHaveAttribute("title", /external skill/i);
  });

  test("nonportable relabels the export action to Export as Portable", async ({ page }) => {
    await openNonPortable(page);
    await openToolbarMenu(page);
    await expect(page.locator("#btnSaveHtmlTop")).toHaveText("Export as Portable");
  });

  test("Help opens a dialog describing the features and closes with Escape", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    const help = page.locator(".cm-help");
    await expect(help).toBeVisible();
    await expect(help).toContainText("Not portable");
    await expect(help).toContainText("Navigation");
    await page.keyboard.press("Escape");
    await expect(page.locator(".cm-help")).toHaveCount(0);
  });

  test("the Help modal title includes the layer version", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    const heading = page.locator(".cm-help .cm-help-head h2");
    await expect(heading).toBeVisible();
    await expect(heading).toContainText(/Commentable HTML v\d+\.\d+\.\d+ - Help/);
  });

  test("every overflow (...) menu item carries a leading icon", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    const menu = page.locator("#toolbarMenu");
    for (const id of ["btnShowTop", "btnSaveHtmlTop", "btnSavePlainTop", "btnExportMdTop", "btnPrintTop", "btnHelpTop"]) {
      const item = menu.locator("#" + id);
      await expect(item.locator("svg"), id).toHaveCount(1);
      // The icon is decorative; the accessible name still comes from the label text.
      await expect(item.locator("svg"), id).toHaveAttribute("aria-hidden", "true");
    }
  });

  test("the overflow menu header shows a decorative brand icon without adding a tab stop (CMH-MENU-ICON-02)", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    const menu = page.locator("#toolbarMenu");
    const icon = menu.locator(".cm-toolbar-menu-brand svg.cm-brand-icon");
    await expect(icon).toHaveCount(1);
    await expect(icon).toHaveAttribute("aria-hidden", "true");
    await expect(icon).toHaveAttribute("focusable", "false");
    expect(await icon.getAttribute("tabindex")).toBeNull();
    const focusableIds = await menu.evaluate((el) => Array.from(el.querySelectorAll("button, a[href], input, textarea, select, [tabindex]"))
      .filter((node) => node.tabIndex >= 0)
      .map((node) => node.id));
    expect(focusableIds).toEqual(["btnShowTop", "btnSaveHtmlTop", "btnExportOfflineTop", "btnSavePlainTop", "btnExportMdTop", "btnPrintTop", "btnHelpTop"]);
  });

  test("the overflow menu header shows the layer version between the badge and brand icon (CMH-MENU-ICON-03)", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    const menu = page.locator("#toolbarMenu");
    const version = menu.locator(".cm-menu-version");
    await expect(version).toHaveCount(1);
    await expect(version).toHaveText(/^v\d+\.\d+\.\d+$/);
    // Same value as the sidebar version indicator (both sourced from CMH_VERSION).
    await expect(version).toHaveText((await page.locator("#cmVersion").textContent()).trim());
    // Positioned between the portability badge (left) and the brand icon (right).
    const order = await menu.locator(".cm-toolbar-menu-head").evaluate((head) => {
      const kids = Array.from(head.children);
      return {
        badge: kids.findIndex((k) => k.id === "cmhModeBadge"),
        ver: kids.findIndex((k) => k.classList.contains("cm-menu-version")),
        brand: kids.findIndex((k) => k.classList.contains("cm-toolbar-menu-brand")),
      };
    });
    expect(order.badge).toBeGreaterThanOrEqual(0);
    expect(order.ver).toBeGreaterThan(order.badge);
    expect(order.brand).toBeGreaterThan(order.ver);
    // Decorative text: not a focusable menu item, so the tab order is unchanged.
    const focusableIds = await menu.evaluate((el) => Array.from(el.querySelectorAll("button, a[href], input, textarea, select, [tabindex]"))
      .filter((node) => node.tabIndex >= 0)
      .map((node) => node.id));
    expect(focusableIds).toEqual(["btnShowTop", "btnSaveHtmlTop", "btnExportOfflineTop", "btnSavePlainTop", "btnExportMdTop", "btnPrintTop", "btnHelpTop"]);
  });

  test("every toolbar and sidebar control has a tooltip", async ({ page }) => {
    await openInline(page);
    await page.click("#btnToggleSidebar"); // open the panel
    for (const id of ["btnCopyAll", "btnSidebarExportMenu", "btnClearAll", "btnCloseSidebar", "btnHelp", "cmTypeBadge"]) {
      const el = page.locator("#" + id);
      // the tooltip text lives in `title` until the styled tooltip layer moves it to
      // data-cmh-tip on first hover/focus, so accept either.
      const tip = (await el.getAttribute("title")) || (await el.getAttribute("data-cmh-tip"));
      expect(tip, id).toBeTruthy();
      expect((tip || "").length, id).toBeGreaterThan(8);
    }
  });

  test("the type bubble reads Portable once every comment is embedded", async ({ page }) => {
    const { html } = stageInline({ source: INLINE });
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "embed me");
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable"); // in storage, not yet embedded
    const comment = await page.evaluate(() =>
      JSON.parse(localStorage.getItem(document.getElementById("commentRoot").dataset.commentKey))[0]);
    // Embed that exact comment (same id + updatedAt) into the file, then reload.
    const embRe = /(<script[^>]*id="embeddedComments"[^>]*>)([\s\S]*?)(<\/script>)/;
    fs.writeFileSync(html, fs.readFileSync(html, "utf8").replace(embRe, (_m, a, _b, c) => a + "\n" + JSON.stringify([comment]) + "\n" + c));
    await page.reload();
    await ready(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
  });

  test("editing an embedded comment drops the type back to Not portable (content, not just id)", async ({ page }) => {
    const { html } = stageInline({ source: INLINE });
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "original text");
    const comment = await page.evaluate(() =>
      JSON.parse(localStorage.getItem(document.getElementById("commentRoot").dataset.commentKey))[0]);
    const embRe = /(<script[^>]*id="embeddedComments"[^>]*>)([\s\S]*?)(<\/script>)/;
    fs.writeFileSync(html, fs.readFileSync(html, "utf8").replace(embRe, (_m, a, _b, c) => a + "\n" + JSON.stringify([comment]) + "\n" + c));
    await page.reload();
    await ready(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Portable");
    // Edit the comment: its updatedAt changes, so the embedded copy is now stale.
    const card = page.locator("#commentList .cm-card").first();
    await card.locator('[data-act="edit"]').click();
    const composer = page.locator(".cm-composer").last();
    await composer.locator("textarea").fill("edited text");
    await composer.locator('[data-act="save"]').click();
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not portable");
  });

  test("Help returns focus to the trigger button when closed", async ({ page }) => {
    await openInline(page);
    await page.click("#btnToggleSidebar"); // open the panel so #btnHelp is on-screen
    await page.locator("#btnHelp").click();
    await expect(page.locator(".cm-help")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".cm-help")).toHaveCount(0);
    expect(await page.evaluate(() => document.activeElement && document.activeElement.id)).toBe("btnHelp");
  });

  test("the TOC side menu and Help modal never leak into a Plain HTML export", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 800 });
    await openInline(page);
    await expect(page.locator("#cmSideToc")).toBeVisible(); // present at runtime
    await openToolbarMenu(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#btnSavePlainTop")]);
    const out = await readDownload(dl);
    // The runtime-generated DOM must be gone (the CSS class selectors legitimately remain
    // in the kept stylesheet - plain export keeps styling, only the commenting DOM/JS go).
    expect(out).not.toContain('id="cmSideToc"');
    expect(out).not.toContain('class="cm-side-toc cm-skip"');
    expect(out).not.toContain("cm-modal-overlay cm-help-overlay");
  });

  test("the TOC side menu falls back to h2/h3 ids when there is no author .cm-toc", async ({ page }) => {
    const { html } = stageInline({ source: INLINE });
    fs.writeFileSync(html, fs.readFileSync(html, "utf8").replace(/<nav class="cm-toc"[\s\S]*?<\/nav>/, ""));
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(html));
    await ready(page);
    const toc = page.locator("#cmSideToc");
    await expect(toc).toBeVisible();
    expect(await toc.locator(".cm-side-toc-list a").count()).toBeGreaterThanOrEqual(2);
  });

  test("Help traps Tab focus inside the modal", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    await expect(page.locator(".cm-help")).toBeVisible();
    // Tab cycles through the modal's focusable elements (close button + About links)
    // and never escapes to the page behind it.
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(() => {
        const box = document.querySelector(".cm-help");
        return !!(box && document.activeElement && box.contains(document.activeElement));
      });
      expect(inside).toBe(true);
    }
    await page.keyboard.press("Escape");
  });

  test("Help opened from the overflow menu returns focus to the menu button", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    await expect(page.locator(".cm-help")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".cm-help")).toHaveCount(0);
    expect(await page.evaluate(() => document.activeElement && document.activeElement.id)).toBe("btnToolbarMenu");
  });

  test("the TOC side menu and Help modal never leak into an Export with embedded comments", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 800 });
    await openInline(page);
    await expect(page.locator("#cmSideToc")).toBeVisible();
    await openToolbarMenu(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#btnSaveHtmlTop")]);
    const out = await readDownload(dl);
    // Export with embedded comments keeps the full layer (the JS is intact), but the
    // runtime-injected side-menu DOM node must not be baked into the exported base.
    expect(out).not.toContain('id="cmSideToc"');
    expect(out).not.toContain('class="cm-side-toc cm-skip"');
    expect(out).toContain("BEGIN: commentable-html - JS"); // the layer is intact (not a plain export)
  });

  test.describe("TOC side menu (wide screen)", () => {
    test.use({ viewport: { width: 1600, height: 800 } });

    test("appears with a numbered link per section and tracks the current section on scroll", async ({ page }) => {
      await openInline(page);
      const toc = page.locator("#cmSideToc");
      await expect(toc).toBeVisible();
      await expect(toc.locator(".cm-side-toc-title")).toHaveText("Navigation");
      expect(await toc.locator(".cm-side-toc-list a").count()).toBeGreaterThanOrEqual(2);
      // Section numbers are shown.
      await expect(toc.locator(".cm-side-toc-list .cm-toc-num").first()).toHaveText(/^\d/);
      await expect(toc.locator("a.is-active")).toContainText("Try it");
      await page.evaluate(() => document.getElementById("diffs").scrollIntoView());
      await expect(toc.locator("a.is-active")).toContainText("Code review diffs");
    });

    test("does not double-number a TOC whose headings already carry numbers", async ({ page }) => {
      const { html } = stageInline({ source: INLINE });
      let n = 0;
      const src = fs.readFileSync(html, "utf8").replace(/<nav class="cm-toc"[\s\S]*?<\/nav>/, (nav) =>
        nav.replace(/(<a href="#[^"]+">)([^<]+)(<\/a>)/g, (_m, a, text, close) => a + (++n) + ". " + text + close));
      fs.writeFileSync(html, src);
      await page.setViewportSize({ width: 1600, height: 800 });
      await page.goto(fileUrl(html));
      await ready(page);
      const toc = page.locator("#cmSideToc");
      await expect(toc).toBeVisible();
      // Author already numbered the sections, so we must NOT add our own number spans...
      await expect(toc.locator(".cm-toc-num")).toHaveCount(0);
      // ...and the first entry shows the author number exactly once (no "1 1." doubling).
      expect((await toc.locator(".cm-side-toc-list a").first().innerText()).trim()).toBe("1. Try it");
    });

    test("collapses to hide the list and a Scroll to Top button returns to the top", async ({ page }) => {
      await openInline(page);
      const toc = page.locator("#cmSideToc");
      await expect(toc).toBeVisible();
      await toc.locator(".cm-side-toc-toggle").click();
      await expect(toc.locator(".cm-side-toc-list")).toBeHidden();
      await expect(toc.locator(".cm-side-toc-toggle")).toHaveText("Navigation \u00bb"); // Navigation >> when collapsed
      await toc.locator(".cm-side-toc-toggle").click();
      await expect(toc.locator(".cm-side-toc-toggle")).toHaveText("\u00ab"); // << collapse chevron when open
      // Scroll to Bottom, then Scroll to Top (smooth scroll: poll for settle).
      await toc.locator(".cm-side-toc-top", { hasText: "Scroll to Bottom" }).click();
      await page.waitForFunction(() => window.scrollY > 200, null, { timeout: 3000 });
      await toc.locator(".cm-side-toc-top", { hasText: "Scroll to Top" }).click();
      await page.waitForFunction(() => window.scrollY < 80, null, { timeout: 3000 });
      expect(await page.evaluate(() => window.scrollY)).toBeLessThan(80);
    });
  });

  test("the TOC side menu is hidden on narrow screens", async ({ page }) => {
    await page.setViewportSize({ width: 1000, height: 800 });
    await openInline(page);
    await expect(page.locator("#cmSideToc")).toBeHidden();
  });
});
