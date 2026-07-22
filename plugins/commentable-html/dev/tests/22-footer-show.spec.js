import { test, expect } from "@playwright/test";
import { openInline, openToolbarMenu, ready, readDownload, installClipboardCapture, stageInline, fileUrl, lastCopied } from "./helpers.js";

// Inject the provenance session stamp the authoring tools write, so the footer copy control renders.
function withSession(html, { sid = "sess-abc-123", agent = "copilot" } = {}) {
  const metas = '<meta name="commentable-html-session-id" content="' + sid + '" />'
    + (agent ? '<meta name="commentable-html-agent" content="' + agent + '" />' : "");
  return html.replace(/<head[^>]*>/i, (m) => m + "\n" + metas);
}
async function openWithSession(page, opts) {
  const { html } = stageInline({ mutate: (h) => withSession(h, opts) });
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
}

test.describe("attribution footer + Show affordance", () => {
  test("the footer shows version and a Help link; attribution lives in Help", async ({ page }) => {
    await openInline(page);
    const footer = page.locator("#cmFooter");
    await expect(footer).toBeVisible();
    await expect(footer).toContainText(/Commentable HTML v\d+\.\d+\.\d+/);
    // The footer has two links: the brand mark and the Report-an-issue link (CMH-FOOT-05).
    await expect(footer).not.toContainText("Authored by");
    await expect(footer.locator("a")).toHaveCount(2);
    await expect(footer.locator("a.cm-brand-link")).toHaveCount(1);
    await expect(footer.locator('a.cm-footer-report[href*="issues/new?template=plugin-issue.yml"]')).toHaveCount(1);
    // The footer Help & about button opens the Help modal, which carries the attribution.
    await footer.locator(".cm-footer-help").click();
    const help = page.locator(".cm-help");
    await expect(help).toBeVisible();
    await expect(help).toContainText(/authored by Uri Kanonov/i);
    await expect(help.locator('a[href="https://github.com/urikanonov/ai-marketplace"]')).toHaveCount(1);
    await expect(help.locator('a[href*="issues/new?template=plugin-issue.yml"]')).toHaveCount(1);
    for (const a of await help.locator('a[href*="github.com/urikanonov"]').all()) {
      await expect(a).toHaveAttribute("rel", /noopener/);
      await expect(a).toHaveAttribute("target", "_blank");
    }
  });

  test("the footer shows the brand icon and the generated timestamp", async ({ page }) => {
    await openInline(page);
    const footer = page.locator("#cmFooter");
    await expect(footer).toBeVisible();
    await expect(footer.locator(".cm-brand-icon")).toHaveCount(1);
    await expect(footer).toContainText(/Generated /);
  });

  test("the footer shows a Report an issue link to the right of Help (CMH-FOOT-05)", async ({ page }) => {
    await openInline(page);
    const footer = page.locator("#cmFooter");
    const report = footer.locator("a.cm-footer-report");
    await expect(report).toHaveCount(1);
    await expect(report).toHaveAttribute(
      "href",
      "https://github.com/urikanonov/ai-marketplace/issues/new?template=plugin-issue.yml"
    );
    await expect(report).toHaveAttribute("target", "_blank");
    await expect(report).toHaveAttribute("rel", /noopener/);
    await expect(report).toHaveAttribute("rel", /noreferrer/);
    await expect(report).toHaveText(/Report an issue/i);
    // The Report link sits to the RIGHT of the Help & about control.
    const helpBox = await footer.locator(".cm-footer-help").boundingBox();
    const reportBox = await report.boundingBox();
    expect(reportBox.x).toBeGreaterThan(helpBox.x);
  });

  test("the Report an issue link does not leak into a Plain HTML export (CMH-FOOT-05)", async ({ page }) => {
    await openInline(page);
    await expect(page.locator("#cmFooter a.cm-footer-report")).toHaveCount(1);
    await openToolbarMenu(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#btnSavePlainTop")]);
    const out = await readDownload(dl);
    // The footer is cm-skip chrome, so its Report link markup is stripped from a Plain export.
    expect(out).not.toContain("cm-footer-report");
    expect(out).not.toContain("issues/new?template=plugin-issue.yml");
  });

  test("the brand icon shows in the panel meta row and a favicon is set", async ({ page }) => {
    await openInline(page);
    await expect(page.locator(".cm-sidebar .head-meta .cm-brand-icon")).toHaveCount(1);
    const favicon = await page.evaluate(() => {
      const l = document.querySelector('link[rel="icon"]');
      return l ? l.getAttribute("href") : null;
    });
    expect(favicon).toBeTruthy();
    expect(favicon).toContain("image/svg+xml");
  });

  test("the footer brand and the sidebar meta brand icon link to the project site in a new tab", async ({ page }) => {
    await openInline(page);
    const SITE = "https://urikanonov.github.io/ai-marketplace/commentable-html/";
    const footerBrand = page.locator("#cmFooter a.cm-brand-link");
    await expect(footerBrand).toHaveCount(1);
    await expect(footerBrand).toHaveAttribute("href", SITE);
    await expect(footerBrand).toHaveAttribute("target", "_blank");
    await expect(footerBrand).toHaveAttribute("rel", /noopener/);
    await expect(footerBrand).toHaveAttribute("rel", /noreferrer/);
    await expect(footerBrand).toHaveAttribute("aria-label", "commentable-html project site (opens in a new tab)");
    // The footer brand wraps both the icon and the versioned name.
    await expect(footerBrand.locator(".cm-brand-icon")).toHaveCount(1);
    await expect(footerBrand).toContainText(/Commentable HTML v\d+\.\d+\.\d+/);
    // The sidebar meta-row brand icon is the same link.
    const sideBrand = page.locator(".cm-sidebar .head-meta a.cm-brand-link");
    await expect(sideBrand).toHaveCount(1);
    await expect(sideBrand).toHaveAttribute("href", SITE);
    await expect(sideBrand).toHaveAttribute("target", "_blank");
    await expect(sideBrand).toHaveAttribute("rel", /noopener/);
    await expect(sideBrand.locator(".cm-brand-icon")).toHaveCount(1);
  });

  test("the brand site link does not leak into a Plain HTML export", async ({ page }) => {
    await openInline(page);
    await openToolbarMenu(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#btnSavePlainTop")]);
    const out = await readDownload(dl);
    expect(out).not.toContain("urikanonov.github.io/ai-marketplace/commentable-html");
    expect(out).not.toContain('aria-label="commentable-html project site (opens in a new tab)"');
  });

  test("the footer does not leak into a Plain HTML export", async ({ page }) => {
    await openInline(page);
    await expect(page.locator("#cmFooter")).toBeVisible();
    await openToolbarMenu(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#btnSavePlainTop")]);
    const out = await readDownload(dl);
    expect(out).not.toContain('id="cmFooter"');
  });

  test("the footer copy-session icon copies the creating agent's session id (CMH-FOOT-04)", async ({ page }) => {
    await openWithSession(page, { sid: "sess-abc-123", agent: "copilot" });
    const btn = page.locator("#cmFooter .cm-footer-copy-session");
    await expect(btn).toHaveCount(1);
    await expect(btn).toHaveAttribute("aria-label", "Copy Copilot session id");
    await btn.click();
    expect(await lastCopied(page)).toBe("sess-abc-123");
    await expect(page.locator("#toast")).toContainText(/Session id copied/i);
    // The session-copy control must not leave two separators adjacent (CMH-FOOT-04).
    const adjacentSeps = await page.evaluate(() => {
      const kids = [...document.querySelectorAll("#cmFooter > *")];
      return kids.some((el, i) => i > 0
        && el.classList.contains("cm-footer-sep")
        && kids[i - 1].classList.contains("cm-footer-sep"));
    });
    expect(adjacentSeps).toBe(false);
  });

  test("the copy-session tooltip names the agent (Claude) (CMH-FOOT-04)", async ({ page }) => {
    await openWithSession(page, { sid: "cl-xyz", agent: "claude" });
    const btn = page.locator("#cmFooter .cm-footer-copy-session");
    await expect(btn).toHaveAttribute("aria-label", "Copy Claude session id");
    await expect(btn).toHaveAttribute("data-cmh-tip", "Copy Claude session id");
  });

  test("the footer copy-session icon is absent without a session-id stamp (CMH-FOOT-04)", async ({ page }) => {
    await openInline(page);
    await expect(page.locator("#cmFooter")).toBeVisible();
    await expect(page.locator("#cmFooter .cm-footer-copy-session")).toHaveCount(0);
  });

  test("the copy-session control does not leak into a Plain HTML export (CMH-FOOT-04)", async ({ page }) => {
    await openWithSession(page, { sid: "sess-abc-123", agent: "copilot" });
    await expect(page.locator("#cmFooter .cm-footer-copy-session")).toHaveCount(1);
    await openToolbarMenu(page);
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#btnSavePlainTop")]);
    const out = await readDownload(dl);
    // The interactive control is runtime chrome inside #cmFooter, so it is stripped; the
    // runtime-composed button aria-label must not appear in the plain export.
    expect(out).not.toContain('id="cmFooter"');
    expect(out).not.toContain("Copy Copilot session id");
  });

  test("the overflow-menu Comments button reopens the panel", async ({ page }) => {
    await openInline(page);
    // Ensure the panel is closed first (the toolbar toggle is hidden while it is open).
    if (await page.evaluate(() => document.body.classList.contains("sidebar-open"))) {
      await page.click("#btnCloseSidebar");
    }
    await expect(page.locator("body")).not.toHaveClass(/sidebar-open/);
    await openToolbarMenu(page);
    await page.click("#btnShowTop");
    await expect(page.locator("body")).toHaveClass(/sidebar-open/);
  });

  test("the collapsed toolbar toggle reads Comments and gets a filled bubble", async ({ page }) => {
    await openInline(page);
    if (await page.evaluate(() => document.body.classList.contains("sidebar-open"))) {
      await page.click("#btnCloseSidebar");
    }
    const toggle = page.locator("#btnToggleSidebar");
    await expect(toggle).toHaveText("Comments");
    // Collapsed reopen button is filled (a non-transparent background) so it stands out.
    const bg = await toggle.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(bg).not.toBe("rgba(0, 0, 0, 0)");
    expect(bg).not.toBe("transparent");
  });
});
