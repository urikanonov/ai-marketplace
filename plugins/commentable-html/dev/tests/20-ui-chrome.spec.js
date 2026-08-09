// Sidebar version indicator, document-type bubble, Help dialog, per-button tooltips,
// and the wide-screen table-of-contents side menu (scroll-spy, collapse, back-to-top).
import { test, expect } from "@playwright/test";
import { openInline, openNonShareable, openToolbarMenu, addTextComment, ready, fileUrl, stageInline, readDownload, INLINE } from "./helpers.js";
import fs from "fs";

const SITE_URL = "https://urikanonov.github.io/ai-marketplace/commentable-html/";
const SITE_LINK_LABEL = "Open Commentable HTML Site";
const SITE_LINK_NAME = SITE_LINK_LABEL + " (opens in a new tab)";
// Identify each focusable by its id, falling back to a STABLE identity for id-less controls
// (the brand link) rather than its class string, which a class reorder would break. Every
// descendant is enumerated, so an id-less tab stop of ANY tag (summary, iframe, contenteditable)
// is still seen rather than filtered away.
const MENU_FOCUS_IDENTITY = (el) => Array.from(el.querySelectorAll("*"))
  .filter((node) => node.tabIndex >= 0)
  .map((node) => node.id || (node.matches("a.cm-brand-link") ? "brand-site-link" : node.tagName.toLowerCase()));
const MENU_ACTION_IDS = ["btnShowTop", "btnSaveHtmlTop", "btnExportOfflineTop", "btnSavePlainTop", "btnExportMdTop", "btnPrintTop", "btnStorageTop", "btnClearAllTop", "btnHelpTop"];
const TOOLBAR_MARK = ".cm-toolbar > a.cm-brand-link";
const MENU_MARK = "#toolbarMenu a.cm-brand-link.cm-toolbar-menu-brand";

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

  test("the type bubble reads Shareable for an inline document with no comments", async ({ page }) => {
    await openInline(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Shareable");
  });

  test("adding a not-yet-embedded comment makes the type Not shareable", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, "#commentRoot p", "a fresh comment lives only in storage");
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not shareable");
    // The bubble explains WHY it is not shareable.
    await expect(page.locator("#cmTypeBadge")).toHaveAttribute("title", /not embedded/i);
  });

  test("the type bubble reads Not shareable for an nonshareable document", async ({ page }) => {
    await openNonShareable(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not shareable");
    await expect(page.locator("#cmTypeBadge")).toHaveAttribute("title", /external skill/i);
  });

  test("nonshareable relabels the export action to Export as Shareable", async ({ page }) => {
    await openNonShareable(page);
    await openToolbarMenu(page);
    await expect(page.locator("#btnSaveHtmlTop")).toHaveText("Export as Shareable");
  });

  test("Help opens a dialog describing the features and closes with Escape", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    const help = page.locator(".cm-help");
    await expect(help).toBeVisible();
    await expect(help).toContainText("Not shareable");
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

  test("the toolbar brand mark links to the project site left of the overflow button (CMH-MENU-ICON-04)", async ({ page }) => {
    await openInline(page);
    const link = page.locator(".cm-toolbar > a.cm-brand-link");
    await expect(link).toHaveCount(1);
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", SITE_URL);
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", /noopener/);
    await expect(link).toHaveAttribute("rel", /noreferrer/);
    // the tooltip text lives in `title` until the styled tooltip layer moves it to data-cmh-tip.
    const tip = (await link.getAttribute("title")) || (await link.getAttribute("data-cmh-tip"));
    expect(tip).toBe(SITE_LINK_LABEL);
    await expect(link).toHaveAttribute("aria-label", SITE_LINK_NAME);
    // The icon inside is decorative, so the link's own name and tooltip win over the version bubble.
    const icon = link.locator("svg.cm-brand-icon");
    await expect(icon).toHaveCount(1);
    await expect(icon).toHaveAttribute("aria-hidden", "true");
    await expect(icon).toHaveAttribute("focusable", "false");
    expect(await icon.getAttribute("data-cmh-tip")).toBeNull();
    // It sits immediately before the three-dot overflow button.
    const nextClass = await link.evaluate((el) => (el.nextElementSibling ? el.nextElementSibling.className : ""));
    expect(nextClass).toContain("cm-toolbar-more");
  });

  test("clicking the toolbar brand mark leaves the overflow menu closed (CMH-MENU-ICON-04)", async ({ page }) => {
    await openInline(page);
    const link = page.locator(".cm-toolbar > a.cm-brand-link");
    // Prove INVARIANCE across the click, not just the final state.
    await expect(page.locator("#toolbarMenu")).toBeHidden();
    // Keep the click hermetic: the anchor still carries its real href/target, but the
    // navigation is cancelled so no new tab is opened during the assertion.
    await link.evaluate((el) => el.addEventListener("click", (e) => e.preventDefault()));
    await link.click();
    await expect(page.locator("#toolbarMenu")).toBeHidden();
    await expect(page.locator("#btnToolbarMenu")).toHaveAttribute("aria-expanded", "false");
  });

  test("the overflow menu header brand mark links to the project site (CMH-MENU-ICON-02)", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    const menu = page.locator("#toolbarMenu");
    const brand = menu.locator("a.cm-brand-link.cm-toolbar-menu-brand");
    await expect(brand).toHaveCount(1);
    await expect(brand).toBeVisible();
    await expect(brand).toHaveAttribute("href", SITE_URL);
    await expect(brand).toHaveAttribute("target", "_blank");
    await expect(brand).toHaveAttribute("rel", /noopener/);
    await expect(brand).toHaveAttribute("rel", /noreferrer/);
    const tip = (await brand.getAttribute("title")) || (await brand.getAttribute("data-cmh-tip"));
    expect(tip).toBe(SITE_LINK_LABEL);
    await expect(brand).toHaveAttribute("aria-label", SITE_LINK_NAME);
    const icon = brand.locator("svg.cm-brand-icon");
    await expect(icon).toHaveCount(1);
    await expect(icon).toHaveAttribute("aria-hidden", "true");
    await expect(icon).toHaveAttribute("focusable", "false");
    expect(await icon.getAttribute("data-cmh-tip")).toBeNull();
    expect(await icon.getAttribute("tabindex")).toBeNull();
    // The brand link is the header's only added tab stop; the action items keep their order.
    expect(await menu.evaluate(MENU_FOCUS_IDENTITY)).toEqual(["brand-site-link", ...MENU_ACTION_IDS]);
  });

  // Both marks get the same two behaviors, so the checks live in helpers and each test keeps a
  // literal title (the spec-citation gate resolves literal titles, not template literals).
  const expectSiteTooltip = async (page, selector) => {
    // The runtime tooltip layer walks UP from the hovered node, so the decorative icon must not
    // shadow its own link with the "Commentable HTML v<version>" bubble it carries elsewhere.
    await page.locator(selector).hover();
    await expect(page.locator(".cm-tooltip.is-visible")).toHaveText(SITE_LINK_LABEL);
  };
  const expectOpensSite = async (page, context, selector) => {
    // The site is never actually fetched: the whole origin is intercepted (the document is
    // served a local stub, any other request on it is aborted), so the spec stays hermetic
    // while still proving the link really navigates to CMH_SITE_URL.
    await context.route("https://urikanonov.github.io/**", (route) => (
      route.request().url() === SITE_URL
        ? route.fulfill({ status: 200, contentType: "text/html", body: "<html><body>stub</body></html>" })
        : route.abort()
    ));
    const [popup] = await Promise.all([
      context.waitForEvent("page"),
      page.locator(selector).click(),
    ]);
    try {
      // The page event fires as soon as the tab exists (often still about:blank), so poll
      // rather than reading the URL once.
      await expect(popup).toHaveURL(SITE_URL);
    } finally {
      await popup.close();
    }
  };

  test("Help advertises the brand marks only on a document that can show them (CMH-MENU-ICON-04)", async ({ page }) => {
    await openInline(page);
    const bullet = page.locator(".cm-help li", { hasText: "comment-bubble mark" });
    await openToolbarMenu(page);
    await page.click("#btnHelpTop");
    await expect(bullet).toHaveCount(1);
    await page.keyboard.press("Escape");
    // A deck hides the whole floating toolbar, so Help must stop naming a mark the reader cannot
    // reach. The gate is read when Help is built, so flipping the mode before reopening is enough.
    await page.evaluate(() => document.getElementById("commentRoot").setAttribute("data-cmh-mode", "deck"));
    // A deck hides the toolbar the Help trigger lives in, so drive the same handler directly.
    await page.evaluate(() => document.querySelector(".cm-footer-help").click());
    await expect(page.locator(".cm-help")).toHaveCount(1);
    await expect(bullet).toHaveCount(0);
  });

  test("hovering the toolbar brand mark shows the site tooltip, not the version bubble (CMH-MENU-ICON-04)", async ({ page }) => {
    await openInline(page);
    await expectSiteTooltip(page, TOOLBAR_MARK);
  });

  test("hovering the overflow menu brand mark shows the site tooltip, not the version bubble (CMH-MENU-ICON-02)", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await expectSiteTooltip(page, MENU_MARK);
  });

  test("activating the toolbar brand mark opens the project site (CMH-MENU-ICON-04)", async ({ page, context }) => {
    await openInline(page);
    await expectOpensSite(page, context, TOOLBAR_MARK);
  });

  test("activating the overflow menu brand mark opens the site and returns focus to the trigger (CMH-MENU-ICON-02)", async ({ page, context }) => {
    await openInline(page);
    await openToolbarMenu(page);
    await expectOpensSite(page, context, MENU_MARK);
    // This mark's own click closes the menu it lives in, so focus must land on the still-visible
    // trigger rather than being dropped on <body>.
    await expect(page.locator("#toolbarMenu")).toBeHidden();
    await expect(page.locator("#btnToolbarMenu")).toBeFocused();
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
    // Positioned between the shareability badge (left) and the brand icon (right).
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
    // Decorative header text does not alter the interactive control order (the id-less brand
    // link is identified too, so an unexpected id-less tab stop cannot slip past this guard).
    expect(await menu.evaluate(MENU_FOCUS_IDENTITY)).toEqual(["brand-site-link", ...MENU_ACTION_IDS]);
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

  test("the type bubble reads Shareable once every comment is embedded", async ({ page }) => {
    const { html } = stageInline({ source: INLINE });
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "embed me");
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not shareable"); // in storage, not yet embedded
    const comment = await page.evaluate(() => {
      const root = document.getElementById("commentRoot");
      const raw = localStorage.getItem(root.dataset.commentKey + "::z") || localStorage.getItem(root.dataset.commentKey);
      return JSON.parse(window.__cmhStorageCodec.decode(raw).json)[0];
    });
    // Embed that exact comment (same id + updatedAt) into the file, then reload.
    const embRe = /(<script[^>]*id="embeddedComments"[^>]*>)([\s\S]*?)(<\/script>)/;
    fs.writeFileSync(html, fs.readFileSync(html, "utf8").replace(embRe, (_m, a, _b, c) => a + "\n" + JSON.stringify([comment]) + "\n" + c));
    await page.reload();
    await ready(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Shareable");
  });

  test("editing an embedded comment drops the type back to Not shareable (content, not just id)", async ({ page }) => {
    const { html } = stageInline({ source: INLINE });
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#commentRoot p", "original text");
    const comment = await page.evaluate(() => {
      const root = document.getElementById("commentRoot");
      const raw = localStorage.getItem(root.dataset.commentKey + "::z") || localStorage.getItem(root.dataset.commentKey);
      return JSON.parse(window.__cmhStorageCodec.decode(raw).json)[0];
    });
    const embRe = /(<script[^>]*id="embeddedComments"[^>]*>)([\s\S]*?)(<\/script>)/;
    fs.writeFileSync(html, fs.readFileSync(html, "utf8").replace(embRe, (_m, a, _b, c) => a + "\n" + JSON.stringify([comment]) + "\n" + c));
    await page.reload();
    await ready(page);
    await expect(page.locator("#cmTypeBadge")).toHaveText("Shareable");
    // Edit the comment: its updatedAt changes, so the embedded copy is now stale.
    const card = page.locator("#commentList .cm-card").first();
    await card.locator('[data-act="edit"]').click();
    const editor = card.locator(".cm-entry-root .cm-reply-compose");
    await editor.locator("textarea").fill("edited text");
    await editor.locator(".cm-reply-save").click();
    await expect(page.locator("#cmTypeBadge")).toHaveText("Not shareable");
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
